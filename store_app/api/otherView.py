from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser


from django.db import transaction
from django.db.models import Sum, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone

from ..models import *
from ..serializers import *
from ..utils import is_popular_product

def _mutable_payload(data):
    if hasattr(data, "copy"):
        data = data.copy()
        if hasattr(data, "_mutable"):
            data._mutable = True
        return data
    return dict(data)

def _first_value(data, *keys):
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None

def _reason_provided(value):
    if value in (None, ""):
        return False
    return str(value).strip().lower() not in {"0", "false", "no", "off", "n", "none", "null"}

def _claim_to_status(value):
    value = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    if value in {"approved", "approve"}:
        return "APPROVED"
    if value in {"not approved", "not approve", "rejected", "reject"}:
        return "NOT_APPROVED"
    if value in {"in progress", "progress", "pending"}:
        return "IN_PROGRESS"
    return None

def _claim_to_choice(value):
    value = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    if value in {"claim", "claimed", "clamed", "yes", "y"}:
        return "CLAIMED"
    if value in {"not claim", "not claimed", "not clamed", "no claim", "not clam", "no", "n"}:
        return "NOT_CLAIMED"
    if value in {"claimed", "not_claimed"}:
        return value.upper()
    return None

def _date_only(value):
    if value in (None, ""):
        return value
    value = str(value)
    return value.split("T", 1)[0].split(" ", 1)[0]

def _reason_from_payload(data, include_customer_error=True):
    if data.get("return_reason"):
        return data.get("return_reason")
    if _reason_provided(data.get("agent_error")):
        return "AGENT_ERROR"
    if _reason_provided(data.get("lack_of_stock")):
        return "LACK_OF_STOCK"
    if include_customer_error and _reason_provided(data.get("customer_error")):
        return "CUSTOMER_ERROR"
    return None

def _attach_return_media(payload, data, files):
    media = files.get("return_photo_video") or files.get("return_photo") or files.get("return_video")
    media_path = _first_value(data, "return_photo_video", "return_photo", "return_video")
    media_value = media or media_path
    if not media_value:
        return
    name = getattr(media_value, "name", str(media_value)).lower()
    if name.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
        payload["return_video"] = media_value
    else:
        payload["return_photo"] = media_value

def _receive_return_stock(return_record, source):
    product = return_record.product
    order = return_record.order
    qty = return_record.quantity
    condition = return_record.condition

    sold_units = list(
        ProductUnit.objects
        .select_for_update()
        .filter(product=product, order=order, status="sold")
        .order_by("serial_number")[:qty]
    )

    if len(sold_units) < qty:
        qty = len(sold_units)

    unit_ids = [unit.id for unit in sold_units]

    if condition == "SAFE":
        ProductUnit.objects.filter(id__in=unit_ids).update(
            status="in_stock",
            order=None,
        )
        inv, _ = Inventory.objects.get_or_create(product=product)
        inv.quantity += qty
        inv.save()
        StockMovement.objects.create(
            product=product,
            delta=qty,
            reason="RETURN",
            condition="OK",
            note=f"{source} safe return received. Serials: {[u.serial_number for u in sold_units]}",
        )
        return "in_stock", sold_units

    ProductUnit.objects.filter(id__in=unit_ids).update(
        status="damaged",
        order=None,
    )
    dmg, _ = DamageInventory.objects.get_or_create(product=product)
    dmg.quantity += qty
    dmg.save()
    StockMovement.objects.create(
        product=product,
        delta=-qty,
        reason="RETURN",
        condition=condition,
        note=f"{source} {condition} return received. Serials: {[u.serial_number for u in sold_units]}",
    )
    return "damaged", sold_units

def _mark_return_received(return_record, source, remarks=None):
    new_status, sold_units = _receive_return_stock(return_record, source)
    return_record.return_status = "APPROVED"
    return_record.return_receive_date = return_record.return_receive_date or timezone.localdate()
    if remarks:
        return_record.remarks = remarks
    if hasattr(return_record, "refund_status"):
        return_record.refund_status = "REFUNDED"
    return_record.save()

    order = return_record.order
    order.order_status = 8
    order.save(update_fields=["order_status"])
    OrderStatus.objects.create(
        order_id=order.id,
        status=8,
        json={"message": f"{source} return received"},
    )

    response = {
        "message": f"{source} return received successfully",
        "id": return_record.id,
        "return_status": return_record.return_status,
        "serials_processed": [unit.serial_number for unit in sold_units],
        "new_status": new_status,
    }
    if hasattr(return_record, "refund_status"):
        response["refund_status"] = return_record.refund_status
    return response

def _normalize_return_create_payload(data, files, return_type):
    payload = _mutable_payload(data)

    if return_type == "customer":
        order_id = _first_value(payload, "order_id", "order")
        product_id = _first_value(payload, "product_id", "product")
        if order_id is not None:
            payload["order_id"] = order_id
        if product_id is not None:
            payload["product_id"] = product_id
    else:
        order_id = _first_value(payload, "order", "order_id")
        product_id = _first_value(payload, "product", "product_id")
        if order_id is not None:
            payload["order"] = order_id
        if product_id is not None:
            payload["product"] = product_id

    claim_status = _claim_to_status(payload.get("claim"))
    claim_choice = _claim_to_choice(
        _first_value(payload, "claim_status", "claim_type", "claim_choice")
    )
    if claim_status:
        payload["return_status"] = claim_status

    claim_amount = payload.get("claim_amount")
    if claim_amount not in (None, ""):
        if return_type == "customer":
            payload["refund_amount"] = claim_amount
        else:
            payload["return_amount"] = claim_amount
            payload["claim_amount"] = claim_amount

    receive_date = _first_value(payload, "return_recive_date", "return_receive_date")
    if receive_date is not None:
        payload["return_receive_date"] = _date_only(receive_date)

    reason = _reason_from_payload(payload, include_customer_error=(return_type == "customer"))
    if reason:
        payload["return_reason"] = reason

    remarks = _first_value(payload, "rmark", "remark", "remarks")
    if remarks is not None:
        payload["remarks"] = remarks

    if return_type == "customer":
        for key in ("claim", "claim_status", "claim_type", "claim_choice", "claim_amount", "return_recive_date", "return_photo_video", "agent_error", "lack_of_stock", "customer_error", "rmark", "remark"):
            payload.pop(key, None)
    else:
        if claim_choice:
            payload["claim_status"] = claim_choice

        if payload.get("claim_status") == "CLAIMED" and claim_status == "APPROVED":
            payload["claim_status"] = "CLAIMED"
            payload["claim_result"] = "RECEIVED"
        elif payload.get("claim_status") == "CLAIMED" and claim_status == "NOT_APPROVED":
            payload["claim_status"] = "CLAIMED"
            payload["claim_result"] = "REJECTED"
        elif payload.get("claim_status") == "NOT_CLAIMED":
            payload["claim_result"] = None
            payload["claim_amount"] = None

        for key in ("claim", "claim_type", "claim_choice", "return_recive_date", "return_photo_video", "agent_error", "lack_of_stock", "customer_error", "rmark", "remark", "product_id", "order_id"):
            payload.pop(key, None)

    _attach_return_media(payload, data, files)
    return payload

def _latest_order_status_code(order):
    latest = (
        OrderStatus.objects
        .filter(order_id=order.id)
        .order_by("-created_at")
        .first()
    )
    return latest.status if latest else order.order_status

class LowStockProductView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Popular product  -> qty <= 10
        Unpopular product -> qty <= 5
        """

        results = []

        inventories = Inventory.objects.select_related("product")

        for inv in inventories:
            product = inv.product
            qty = inv.quantity

            popular = is_popular_product(product)
            threshold = 10 if popular else 5

            if qty <= threshold:
                results.append({
                    "product_id": product.id,
                    "sku": product.sku,
                    "name": product.name,
                    "quantity": qty,
                    "popular": popular,
                    "threshold": threshold,
                })

        return Response({
            "count": len(results),
            "results": results
        })



class ProductListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        low_stock = request.GET.get("low_stock")
        best_selling = request.GET.get("best_selling")
        limit = int(request.GET.get("limit", 10))

        products = Product.objects.select_related("inventory")

        # 🔥 BEST SELLING FILTER (MULTIPLE PRODUCTS)
        if best_selling:
            best_ids = (
                OrderItem.objects
                .values("product")
                .annotate(total_sold=Sum("quantity"))
                .order_by("-total_sold")[:limit]
            )
            product_ids = [p["product"] for p in best_ids]
            products = products.filter(id__in=product_ids)

        results = []

        for product in products:
            inventory = getattr(product, "inventory", None)
            qty = inventory.quantity if inventory else 0

            popular = is_popular_product(product)
            threshold = 10 if popular else 5

            # ⚠️ LOW STOCK FILTER
            if low_stock:
                if qty > threshold:
                    continue

            results.append({
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "quantity": qty,
                "popular": popular,
                "threshold": threshold,
            })

        return Response({
            "count": len(results),
            "results": results
        })
    
class VendorDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, vendor_id):
        try:
            vendor = Vendor.objects.get(id=vendor_id)
        except Vendor.DoesNotExist:
            return Response({"error": "Vendor not found"}, status=404)

        # =========================
        # 1️⃣ Vendor Basic Info
        # =========================
        vendor_data = {
            "id": vendor.id,
            "name": vendor.name,
            "city": vendor.city,
            "state": vendor.state,
            "country": vendor.country,
            "gstin": vendor.gst_number,
            "vendor_logo": None,
            "email": vendor.email,
            "mobile": vendor.mobile,
            "firm": vendor.firm_name,
            "address": vendor.address
        }

        # =========================
        # 2️⃣ PERFORMANCE (STATIC / FUTURE)
        # =========================
        performance = {
            "on_time_delivery": 92,
            "quality_rating": 4.5
        }

        # =========================
        # 🔥 3️⃣ OVERALL STATS (NEW)
        # =========================

        # Total bills generated
        total_bills = PurchaseBill.objects.filter(vendor=vendor).count()

        # Total business amount (sum of all purchase bills)
        total_business_amount = (
            PurchaseBill.objects
            .filter(vendor=vendor)
            .aggregate(total=Sum("total_amount"))
            .get("total") or 0
        )

        # Total products purchased (sum of quantities)
        total_products_purchased = (
            PurchaseBillItem.objects
            .filter(bill__vendor=vendor)
            .aggregate(total=Sum("quantity"))
            .get("total") or 0
        )

        stats = {
            "total_bills_generated": total_bills,
            "total_products_purchased": total_products_purchased,
            "total_business_amount": total_business_amount
        }

        # =========================
        # 4️⃣ SUPPLIED PRODUCTS
        # =========================
        supplied_products = []

        products = Product.objects.filter(vendor=vendor).select_related("inventory")

        for product in products:
            total_supplied = (
                PurchaseBillItem.objects
                .filter(product=product)
                .aggregate(total=Sum("quantity"))
                .get("total") or 0
            )

            stock_qty = product.inventory.quantity if hasattr(product, "inventory") else 0

            supplied_products.append({
                "sku": product.sku,
                "product_name": product.name,
                "supplied_qty": total_supplied,
                "remainder_qty": stock_qty
            })

        # =========================
        # 5️⃣ PAST PURCHASE ORDERS
        # =========================
        past_orders = []

        bills = (
            PurchaseBill.objects
            .filter(vendor=vendor)
            .order_by("-created_at")
        )

        for bill in bills:
            items_count = bill.items.aggregate(
                total=Sum("quantity")
            ).get("total") or 0

            past_orders.append({
                "po_number": bill.bill_number,
                "date": bill.bill_date,
                "items": items_count,
                "total_amount": bill.total_amount,
                "status": bill.status
            })

        # =========================
        # ✅ FINAL RESPONSE
        # =========================
        return Response({
            "vendor": vendor_data,
            "stats": stats,                     # 👈 NEW SECTION
            "performance": performance,
            "supplied_products": supplied_products,
            "past_orders": past_orders
        })
    
class CourierReturnCreateView(APIView):
    # permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        payload = _normalize_return_create_payload(request.data, request.FILES, "courier")
        serializer = CourierReturnCreateSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        order = serializer.validated_data["order"]
        if _latest_order_status_code(order) != 3:
            return Response({
                "message": "Courier return can be created only when order is In Transit"
            }, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            save_kwargs = {}
            if not payload.get("return_status"):
                save_kwargs["return_status"] = "IN_PROGRESS"
            courier_return = serializer.save(**save_kwargs)
            courier_return.order.order_status = 6
            courier_return.order.save(update_fields=["order_status"])
            OrderStatus.objects.create(
                order_id=courier_return.order_id,
                status=6,
                json={"message": "Courier return initiated"},
            )

        return Response({
            "message": "Courier return created successfully",
            "id": courier_return.id,
            "return_status": courier_return.return_status,
        }, status=status.HTTP_201_CREATED)


class CourierReturnListView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = CourierReturn.objects.all().order_by("-received_at")

        condition = request.GET.get("condition")
        claim_status = request.GET.get("claim_status")
        claim_result = request.GET.get("claim_result")
        return_status = request.GET.get("return_status")
        order_id = request.GET.get("order_id")

        if condition:
            qs = qs.filter(condition=condition)
        if claim_status:
            qs = qs.filter(claim_status=claim_status)
        if claim_result:
            qs = qs.filter(claim_result=claim_result)
        if return_status:
            qs = qs.filter(return_status=return_status)
        if order_id:
            qs = qs.filter(order_id=order_id)

        serializer = CourierReturnSerializer(qs, many=True)
        return Response(serializer.data)


class CourierReturnUpdateStatusView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    def put(self, request, id):
        return self.patch(request, id)

    def patch(self, request, id):
        try:
            courier_return = CourierReturn.objects.get(id=id)
        except CourierReturn.DoesNotExist:
            return Response({
                "message": "Courier return not found"
            }, status=status.HTTP_404_NOT_FOUND)

        return_status = request.data.get("return_status")
        remarks = request.data.get("remarks")

        valid_status = ["APPROVED", "NOT_APPROVED", "IN_PROGRESS", "RECEIVED"]

        if return_status not in valid_status:
            return Response({
                "message": "Invalid return_status",
                "valid_status": valid_status
            }, status=status.HTTP_400_BAD_REQUEST)

        if courier_return.return_status == "APPROVED":
            return Response({
                "message": "This courier return is already approved"
            }, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            courier_return.return_status = return_status

            if return_status == "RECEIVED":
                return Response(
                    _mark_return_received(courier_return, "Courier", remarks),
                    status=status.HTTP_200_OK,
                )

            if return_status == "APPROVED":
                required_fields = [
                    "return_amount",
                    "return_charges",
                    "return_receive_date",
                    "return_reason",
                ]

                missing_fields = [
                    field for field in required_fields
                    if not request.data.get(field)
                ]

                if not courier_return.return_photo and not request.FILES.get("return_photo"):
                    missing_fields.append("return_photo")

                if not courier_return.return_video and not request.FILES.get("return_video"):
                    missing_fields.append("return_video")

                if missing_fields:
                    return Response({
                        "message": "These fields are required for approved return",
                        "missing_fields": missing_fields
                    }, status=status.HTTP_400_BAD_REQUEST)

                courier_return.return_amount = request.data.get("return_amount")
                courier_return.return_charges = request.data.get("return_charges")
                courier_return.return_receive_date = request.data.get("return_receive_date")
                courier_return.return_reason = request.data.get("return_reason")
                courier_return.remarks = remarks

                if request.FILES.get("return_photo"):
                    courier_return.return_photo = request.FILES.get("return_photo")

                if request.FILES.get("return_video"):
                    courier_return.return_video = request.FILES.get("return_video")

                product = courier_return.product
                order = courier_return.order
                qty = courier_return.quantity
                condition = courier_return.condition

                sold_units = list(
                    ProductUnit.objects
                    .select_for_update()
                    .filter(product=product, order=order, status="sold")
                    .order_by("serial_number")[:qty]
                )

                if len(sold_units) < qty:
                    qty = len(sold_units)

                unit_ids = [u.id for u in sold_units]

                if condition == "SAFE":
                    ProductUnit.objects.filter(id__in=unit_ids).update(
                        status="in_stock",
                        order=None
                    )

                    inv, _ = Inventory.objects.get_or_create(product=product)
                    inv.quantity += qty
                    inv.save()

                    StockMovement.objects.create(
                        product=product,
                        delta=qty,
                        reason="RETURN",
                        condition="OK",
                        note=f"Courier safe return approved. Serials: {[u.serial_number for u in sold_units]}"
                    )

                    new_status = "in_stock"

                else:
                    ProductUnit.objects.filter(id__in=unit_ids).update(
                        status="damaged",
                        order=None
                    )

                    dmg, _ = DamageInventory.objects.get_or_create(product=product)
                    dmg.quantity += qty
                    dmg.save()

                    StockMovement.objects.create(
                        product=product,
                        delta=-qty,
                        reason="RETURN",
                        condition="DAMAGED",
                        note=f"Courier damaged return approved. Serials: {[u.serial_number for u in sold_units]}"
                    )

                    new_status = "damaged"

                courier_return.save()
                order.order_status = 8
                order.save(update_fields=["order_status"])
                OrderStatus.objects.create(
                    order_id=order.id,
                    status=8,
                    json={"message": "Courier return received"},
                )

                return Response({
                    "message": "Courier return approved successfully",
                    "id": courier_return.id,
                    "return_status": courier_return.return_status,
                    "serials_processed": [u.serial_number for u in sold_units],
                    "new_status": new_status,
                }, status=status.HTTP_200_OK)

            if return_status == "NOT_APPROVED":
                courier_return.return_amount = None
                courier_return.return_charges = None
                courier_return.return_receive_date = None
                courier_return.return_photo = None
                courier_return.return_video = None
                courier_return.return_reason = None
                courier_return.remarks = remarks
                courier_return.save()

                return Response({
                    "message": "Courier return marked as not approved",
                    "id": courier_return.id,
                    "return_status": courier_return.return_status,
                }, status=status.HTTP_200_OK)

            if return_status == "IN_PROGRESS":
                if not remarks:
                    return Response({
                        "message": "Remarks is required for in progress"
                    }, status=status.HTTP_400_BAD_REQUEST)

                courier_return.return_amount = None
                courier_return.return_charges = None
                courier_return.return_receive_date = None
                courier_return.return_photo = None
                courier_return.return_video = None
                courier_return.return_reason = None
                courier_return.remarks = remarks
                courier_return.save()

                return Response({
                    "message": "Courier return marked as in progress",
                    "id": courier_return.id,
                    "return_status": courier_return.return_status,
                    "remarks": courier_return.remarks,
                }, status=status.HTTP_200_OK)

# ==================================================================================================
# class CourierReturnCreateView(APIView):
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         serializer = CourierReturnSerializer(data=request.data)
#         serializer.is_valid(raise_exception=True)

#         with transaction.atomic():
#             courier_return = serializer.save()

#             product  = courier_return.product
#             order    = courier_return.order
#             qty      = courier_return.quantity
#             condition = courier_return.condition

#             # ── us order ke sold serials dhundo ───────────────────────────
#             sold_units = list(
#                 ProductUnit.objects
#                 .select_for_update()
#                 .filter(product=product, order=order, status="sold")
#                 .order_by("serial_number")[:qty]
#             )

#             if len(sold_units) < qty:
#                 # Agar sold units kam hain to jo hain unhe hi process karo
#                 qty = len(sold_units)

#             unit_ids = [u.id for u in sold_units]

#             if condition == "SAFE":
#                 # ── serials wapas in_stock karo ───────────────────────────
#                 ProductUnit.objects.filter(id__in=unit_ids).update(
#                     status="in_stock",
#                     order=None
#                 )

#                 # ── inventory badhao ───────────────────────────────────────
#                 inv, _ = Inventory.objects.get_or_create(product=product)
#                 inv.quantity += qty
#                 inv.save()

#                 StockMovement.objects.create(
#                     product=product,
#                     delta=qty,
#                     reason="RETURN",
#                     condition="OK",
#                     note=f"Courier safe return. Serials: {[u.serial_number for u in sold_units]}"
#                 )

#             else:
#                 # ── serials damaged mark karo ─────────────────────────────
#                 ProductUnit.objects.filter(id__in=unit_ids).update(
#                     status="damaged",
#                     order=None
#                 )

#                 # ── damage inventory mein add karo ────────────────────────
#                 dmg, _ = DamageInventory.objects.get_or_create(product=product)
#                 dmg.quantity += qty
#                 dmg.save()

#                 StockMovement.objects.create(
#                     product=product,
#                     delta=-qty,
#                     reason="RETURN",
#                     condition="DAMAGED",
#                     note=f"Courier damaged return. Serials: {[u.serial_number for u in sold_units]}"
#                 )

#         return Response({
#             "message": "Courier return processed successfully",
#             "id": courier_return.id,
#             "condition": condition,
#             "serials_processed": [u.serial_number for u in sold_units],
#             "new_status": "in_stock" if condition == "SAFE" else "damaged",
#         }, status=201)
    # =================================================================================================
# class CourierReturnCreateView(APIView):
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         serializer = CourierReturnSerializer(data=request.data)
#         serializer.is_valid(raise_exception=True)

#         with transaction.atomic():
#             courier_return = serializer.save()

#             product = courier_return.product
#             qty = courier_return.quantity

#             # ✅ SAFE RETURN
#             if courier_return.condition == "SAFE":
#                 inventory, _ = Inventory.objects.get_or_create(product=product)
#                 inventory.quantity += qty
#                 inventory.save()

#                 StockMovement.objects.create(
#                     product=product,
#                     delta=qty,
#                     reason="RETURN",
#                     condition="OK",
#                     note="Safe return received"
#                 )

#                 # 🔥 Barcode regenerate (reuse existing save())
#                 product.barcode = product.sku
#                 product.save()

#             # ❌ DAMAGED RETURN
#             else:
#                 damage, _ = DamageInventory.objects.get_or_create(product=product)
#                 damage.quantity += qty
#                 damage.save()

#                 StockMovement.objects.create(
#                     product=product,
#                     delta=-qty,
#                     reason="RETURN",
#                     condition="DAMAGED",
#                     note="Damaged return received"
#                 )

#         return Response({
#             "message": "Courier return processed successfully",
#             "id": courier_return.id
#         }, status=201)

# class CourierReturnListView(APIView):
#     permission_classes = [IsAuthenticated]

#     def get(self, request):
#         qs = CourierReturn.objects.all().order_by("-received_at")

#         condition = request.GET.get("condition")
#         claim_status = request.GET.get("claim_status")
#         claim_result = request.GET.get("claim_result")

#         if condition:
#             qs = qs.filter(condition=condition)
#         if claim_status:
#             qs = qs.filter(claim_status=claim_status)
#         if claim_result:
#             qs = qs.filter(claim_result=claim_result)

#         serializer = CourierReturnSerializer(qs, many=True)
#         return Response(serializer.data)
# class CourierReturnUpdateStatusView(APIView):
#     permission_classes = [IsAuthenticated]
#     parser_classes = [MultiPartParser, FormParser, JSONParser]

#     def patch(self, request, id):
#         try:
#             courier_return = CourierReturn.objects.get(id=id)
#         except CourierReturn.DoesNotExist:
#             return Response({
#                 "message": "Courier return not found"
#             }, status=status.HTTP_404_NOT_FOUND)

#         return_status = request.data.get("return_status")
#         remark = request.data.get("remark")

#         valid_status = ["approved", "not_approved", "in_progress"]

#         if return_status not in valid_status:
#             return Response({
#                 "message": "Invalid return_status",
#                 "valid_status": valid_status
#             }, status=status.HTTP_400_BAD_REQUEST)

#         if courier_return.return_status == "approved":
#             return Response({
#                 "message": "This courier return is already approved"
#             }, status=status.HTTP_400_BAD_REQUEST)

#         with transaction.atomic():
#             courier_return.return_status = return_status

#             if return_status == "approved":
#                 required_fields = [
#                     "return_amount",
#                     "return_charges",
#                     "return_receive_date",
#                     "customer_return_reason",
#                 ]

#                 missing_fields = [
#                     field for field in required_fields
#                     if not request.data.get(field)
#                 ]
                
#                 if not courier_return.return_photo and not request.FILES.get("return_photo"):
#                     missing_fields.append("return_photo")
#                 if not courier_return.return_video and not request.FILES.get("return_video"):
#                     missing_fields.append("return_video")

#                 if missing_fields:
#                     return Response({
#                         "message": "These fields are required for approved return",
#                         "missing_fields": missing_fields
#                     }, status=status.HTTP_400_BAD_REQUEST)

#                 courier_return.return_amount = request.data.get("return_amount")
#                 courier_return.return_charges = request.data.get("return_charges")
#                 courier_return.return_receive_date = request.data.get("return_receive_date")
#                 courier_return.customer_return_reason = request.data.get("customer_return_reason")
#                 courier_return.remark = remark

#                 if request.FILES.get("return_photo"):
#                     courier_return.return_photo = request.FILES.get("return_photo")

#                 if request.FILES.get("return_video"):
#                     courier_return.return_video = request.FILES.get("return_video")

#                 product = courier_return.product
#                 order = courier_return.order
#                 qty = courier_return.quantity
#                 condition = courier_return.condition

#                 sold_units = list(
#                     ProductUnit.objects
#                     .select_for_update()
#                     .filter(product=product, order=order, status="sold")
#                     .order_by("serial_number")[:qty]
#                 )

#                 if len(sold_units) < qty:
#                     qty = len(sold_units)

#                 unit_ids = [u.id for u in sold_units]

#                 if condition == "SAFE":
#                     ProductUnit.objects.filter(id__in=unit_ids).update(
#                         status="in_stock",
#                         order=None
#                     )

#                     inv, _ = Inventory.objects.get_or_create(product=product)
#                     inv.quantity += qty
#                     inv.save()

#                     StockMovement.objects.create(
#                         product=product,
#                         delta=qty,
#                         reason="RETURN",
#                         condition="OK",
#                         note=f"Courier safe return approved. Serials: {[u.serial_number for u in sold_units]}"
#                     )

#                     new_status = "in_stock"

#                 else:
#                     ProductUnit.objects.filter(id__in=unit_ids).update(
#                         status="damaged",
#                         order=None
#                     )

#                     dmg, _ = DamageInventory.objects.get_or_create(product=product)
#                     dmg.quantity += qty
#                     dmg.save()

#                     StockMovement.objects.create(
#                         product=product,
#                         delta=-qty,
#                         reason="RETURN",
#                         condition="DAMAGED",
#                         note=f"Courier damaged return approved. Serials: {[u.serial_number for u in sold_units]}"
#                     )

#                     new_status = "damaged"

#                 courier_return.save()

#                 return Response({
#                     "message": "Courier return approved successfully",
#                     "id": courier_return.id,
#                     "return_status": courier_return.return_status,
#                     "serials_processed": [u.serial_number for u in sold_units],
#                     "new_status": new_status,
#                 }, status=status.HTTP_200_OK)

#             if return_status == "not_approved":
#                 courier_return.return_amount = None
#                 courier_return.return_charges = None
#                 courier_return.return_receive_date = None
#                 courier_return.return_photo = None
#                 courier_return.return_video = None
#                 courier_return.customer_return_reason = None
#                 courier_return.remark = remark
#                 courier_return.save()

#                 return Response({
#                     "message": "Courier return marked as not approved",
#                     "id": courier_return.id,
#                     "return_status": courier_return.return_status,
#                 }, status=status.HTTP_200_OK)

#             if return_status == "in_progress":
#                 if not remark:
#                     return Response({
#                         "message": "Remark is required for in progress"
#                     }, status=status.HTTP_400_BAD_REQUEST)

#                 courier_return.return_amount = None
#                 courier_return.return_charges = None
#                 courier_return.return_receive_date = None
#                 courier_return.return_photo = None
#                 courier_return.return_video = None
#                 courier_return.customer_return_reason = None
#                 courier_return.remark = remark
#                 courier_return.save()

#                 return Response({
#                     "message": "Courier return marked as in progress",
#                     "id": courier_return.id,
#                     "return_status": courier_return.return_status,
#                     "remark": courier_return.remark,
#                 }, status=status.HTTP_200_OK)

class CourierClaimReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            CourierReturn.objects
            .filter(condition="DAMAGED", claim_status="CLAIMED")
            .values("claim_result")
            .annotate(
                total_cases=Count("id"),
                total_amount=Sum("claim_amount")
            )
        )

        return Response(data)
class CourierFinanceSettlementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        settlements = (
            CourierReturn.objects
            .filter(
                condition="DAMAGED",
                claim_status="CLAIMED",
                claim_result="RECEIVED"
            )
            .values("order__id", "product__name")
            .annotate(
                total_amount=Sum("claim_amount"),
                total_qty=Sum("quantity")
            )
        )

        return Response(settlements)
    
# ==============================================================================================
# class CustomerReturnCreateView(APIView):
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         serializer = CustomerReturnSerializerNew(data=request.data)
#         serializer.is_valid(raise_exception=True)

#         with transaction.atomic():
#             customer_return = serializer.save()

#             product   = customer_return.product
#             order     = customer_return.order
#             qty       = customer_return.quantity
#             condition = customer_return.condition

#             # ── us order ke sold serials dhundo ───────────────────────────
#             sold_units = list(
#                 ProductUnit.objects
#                 .select_for_update()
#                 .filter(product=product, order=order, status="sold")
#                 .order_by("serial_number")[:qty]
#             )

#             if len(sold_units) < qty:
#                 qty = len(sold_units)

#             unit_ids = [u.id for u in sold_units]

#             if condition == "SAFE":
#                 # ── serials wapas in_stock karo ───────────────────────────
#                 ProductUnit.objects.filter(id__in=unit_ids).update(
#                     status="in_stock",
#                     order=None
#                 )

#                 inv, _ = Inventory.objects.get_or_create(product=product)
#                 inv.quantity += qty
#                 inv.save()

#                 StockMovement.objects.create(
#                     product=product,
#                     delta=qty,
#                     reason="RETURN",
#                     condition="OK",
#                     note=f"Customer safe return. Serials: {[u.serial_number for u in sold_units]}"
#                 )

#             else:
#                 # DAMAGED ya LOST dono ke liye serial damaged mark karo ────
#                 ProductUnit.objects.filter(id__in=unit_ids).update(
#                     status="damaged",
#                     order=None
#                 )

#                 dmg, _ = DamageInventory.objects.get_or_create(product=product)
#                 dmg.quantity += qty
#                 dmg.save()

#                 StockMovement.objects.create(
#                     product=product,
#                     delta=-qty,
#                     reason="RETURN",
#                     condition=condition,
#                     note=f"Customer {condition} return. Serials: {[u.serial_number for u in sold_units]}"
#                 )

#         return Response({
#             "message": "Customer return processed successfully",
#             "id": customer_return.id,
#             "condition": condition,
#             "serials_processed": [u.serial_number for u in sold_units],
#             "new_status": "in_stock" if condition == "SAFE" else "damaged",
#         }, status=status.HTTP_201_CREATED)
#     # ====================================================================================================
# # class CustomerReturnCreateView(APIView):
# #     permission_classes = [IsAuthenticated]

# #     def post(self, request):
# #         serializer = CustomerReturnSerializerNew(data=request.data)
# #         serializer.is_valid(raise_exception=True)

# #         with transaction.atomic():
# #             customer_return = serializer.save()

# #             product = customer_return.product
# #             qty = customer_return.quantity

# #             # ✅ SAFE RETURN → inventory back
# #             if customer_return.condition == "SAFE":
# #                 inventory, _ = Inventory.objects.get_or_create(product=product)
# #                 inventory.quantity += qty
# #                 inventory.save()

# #                 StockMovement.objects.create(
# #                     product=product,
# #                     delta=qty,
# #                     reason="RETURN",
# #                     condition="OK",
# #                     note="Customer safe return"
# #                 )

# #                 # Barcode regenerate
# #                 product.barcode = product.sku
# #                 product.save()

# #             # ❌ DAMAGED / LOST
# #             else:
# #                 damage, _ = DamageInventory.objects.get_or_create(product=product)
# #                 damage.quantity += qty
# #                 damage.save()

# #                 StockMovement.objects.create(
# #                     product=product,
# #                     delta=-qty,
# #                     reason="RETURN",
# #                     condition=customer_return.condition,
# #                     note="Customer damaged/lost return"
# #                 )

# #         return Response({
# #             "message": "Customer return processed successfully",
# #             "id": customer_return.id
# #         }, status=status.HTTP_201_CREATED)
# class CustomerReturnListView(APIView):
#     permission_classes = [IsAuthenticated]

#     def get(self, request):
#         qs = CustomerReturnModels.objects.all().order_by("-received_at")

#         condition = request.GET.get("condition")
#         refund_status = request.GET.get("refund_status")

#         if condition:
#             qs = qs.filter(condition=condition)
#         if refund_status:
#             qs = qs.filter(refund_status=refund_status)

#         serializer = CustomerReturnSerializerNew(qs, many=True)
#         return Response(serializer.data)
class CustomerReturnCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        payload = _normalize_return_create_payload(request.data, request.FILES, "customer")
        serializer = CustomerReturnSerializerNew(data=payload)
        serializer.is_valid(raise_exception=True)
        order = get_object_or_404(Order, id=payload.get("order_id"))
        if _latest_order_status_code(order) != 4:
            return Response({
                "message": "Customer return can be created only after order is Delivered"
            }, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            save_kwargs = {}
            if not payload.get("return_status"):
                save_kwargs["return_status"] = "IN_PROGRESS"
            if not payload.get("refund_status"):
                if payload.get("return_status") == "APPROVED":
                    save_kwargs["refund_status"] = "REFUNDED"
                elif payload.get("return_status") == "NOT_APPROVED":
                    save_kwargs["refund_status"] = "REJECTED"
                else:
                    save_kwargs["refund_status"] = "PENDING"
            customer_return = serializer.save(
                **save_kwargs
            )
            customer_return.order.order_status = 7
            customer_return.order.save(update_fields=["order_status"])
            OrderStatus.objects.create(
                order_id=customer_return.order_id,
                status=7,
                json={"message": "Customer return initiated"},
            )

        return Response({
            "message": "Customer return created successfully",
            "id": customer_return.id,
            "return_status": customer_return.return_status,
            "refund_status": customer_return.refund_status,
        }, status=status.HTTP_201_CREATED)


class CustomerReturnListView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = CustomerReturnModels.objects.all().order_by("-received_at")

        condition = request.GET.get("condition")
        refund_status = request.GET.get("refund_status")
        return_status = request.GET.get("return_status")
        order_id = request.GET.get("order_id")

        if condition:
            qs = qs.filter(condition=condition)
        if refund_status:
            qs = qs.filter(refund_status=refund_status)
        if return_status:
            qs = qs.filter(return_status=return_status)
        if order_id:
            qs = qs.filter(order_id=order_id)

        serializer = CustomerReturnSerializerNew(qs, many=True)
        return Response(serializer.data)


class CustomerReturnUpdateStatusView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def put(self, request, id):
        return self.patch(request, id)

    def patch(self, request, id):
        try:
            customer_return = CustomerReturnModels.objects.get(id=id)
        except CustomerReturnModels.DoesNotExist:
            return Response({
                "message": "Customer return not found"
            }, status=status.HTTP_404_NOT_FOUND)

        return_status = request.data.get("return_status")
        remarks = request.data.get("remarks")

        valid_status = ["APPROVED", "NOT_APPROVED", "IN_PROGRESS", "RECEIVED"]

        if return_status not in valid_status:
            return Response({
                "message": "Invalid return_status",
                "valid_status": valid_status
            }, status=status.HTTP_400_BAD_REQUEST)

        if customer_return.return_status == "APPROVED":
            return Response({
                "message": "This customer return is already approved"
            }, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            customer_return.return_status = return_status

            if return_status == "RECEIVED":
                return Response(
                    _mark_return_received(customer_return, "Customer", remarks),
                    status=status.HTTP_200_OK,
                )

            if return_status == "APPROVED":
                required_fields = [
                    "refund_amount",
                    "return_charges",
                    "return_receive_date",
                    "return_reason",
                ]

                missing_fields = [
                    field for field in required_fields
                    if not request.data.get(field)
                ]

                if not customer_return.return_photo and not request.FILES.get("return_photo"):
                    missing_fields.append("return_photo")

                if not customer_return.return_video and not request.FILES.get("return_video"):
                    missing_fields.append("return_video")

                if missing_fields:
                    return Response({
                        "message": "These fields are required for approved return",
                        "missing_fields": missing_fields
                    }, status=status.HTTP_400_BAD_REQUEST)

                customer_return.refund_amount = request.data.get("refund_amount")
                customer_return.return_charges = request.data.get("return_charges")
                customer_return.return_receive_date = request.data.get("return_receive_date")
                customer_return.return_reason = request.data.get("return_reason")
                customer_return.remarks = remarks
                customer_return.refund_status = "REFUNDED"

                if request.FILES.get("return_photo"):
                    customer_return.return_photo = request.FILES.get("return_photo")

                if request.FILES.get("return_video"):
                    customer_return.return_video = request.FILES.get("return_video")

                product = customer_return.product
                order = customer_return.order
                qty = customer_return.quantity
                condition = customer_return.condition

                sold_units = list(
                    ProductUnit.objects
                    .select_for_update()
                    .filter(product=product, order=order, status="sold")
                    .order_by("serial_number")[:qty]
                )

                if len(sold_units) < qty:
                    qty = len(sold_units)

                unit_ids = [u.id for u in sold_units]

                if condition == "SAFE":
                    ProductUnit.objects.filter(id__in=unit_ids).update(
                        status="in_stock",
                        order=None
                    )

                    inv, _ = Inventory.objects.get_or_create(product=product)
                    inv.quantity += qty
                    inv.save()

                    StockMovement.objects.create(
                        product=product,
                        delta=qty,
                        reason="RETURN",
                        condition="OK",
                        note=f"Customer safe return approved. Serials: {[u.serial_number for u in sold_units]}"
                    )

                    new_status = "in_stock"

                else:
                    ProductUnit.objects.filter(id__in=unit_ids).update(
                        status="damaged",
                        order=None
                    )

                    dmg, _ = DamageInventory.objects.get_or_create(product=product)
                    dmg.quantity += qty
                    dmg.save()

                    StockMovement.objects.create(
                        product=product,
                        delta=-qty,
                        reason="RETURN",
                        condition=condition,
                        note=f"Customer {condition} return approved. Serials: {[u.serial_number for u in sold_units]}"
                    )

                    new_status = "damaged"

                customer_return.save()
                order.order_status = 8
                order.save(update_fields=["order_status"])
                OrderStatus.objects.create(
                    order_id=order.id,
                    status=8,
                    json={"message": "Customer return received"},
                )

                return Response({
                    "message": "Customer return approved successfully",
                    "id": customer_return.id,
                    "return_status": customer_return.return_status,
                    "refund_status": customer_return.refund_status,
                    "condition": condition,
                    "serials_processed": [u.serial_number for u in sold_units],
                    "new_status": new_status,
                }, status=status.HTTP_200_OK)

            if return_status == "NOT_APPROVED":
                customer_return.refund_amount = 0
                customer_return.return_charges = None
                customer_return.return_receive_date = None
                customer_return.return_photo = None
                customer_return.return_video = None
                customer_return.return_reason = None
                customer_return.refund_status = "REJECTED"
                customer_return.remarks = remarks
                customer_return.save()

                return Response({
                    "message": "Customer return marked as not approved",
                    "id": customer_return.id,
                    "return_status": customer_return.return_status,
                    "refund_status": customer_return.refund_status,
                }, status=status.HTTP_200_OK)

            if return_status == "IN_PROGRESS":
                if not remarks:
                    return Response({
                        "message": "Remarks is required for in progress"
                    }, status=status.HTTP_400_BAD_REQUEST)

                customer_return.return_charges = None
                customer_return.return_receive_date = None
                customer_return.return_photo = None
                customer_return.return_video = None
                customer_return.return_reason = None
                customer_return.refund_status = "PENDING"
                customer_return.remarks = remarks
                customer_return.save()

                return Response({
                    "message": "Customer return marked as in progress",
                    "id": customer_return.id,
                    "return_status": customer_return.return_status,
                    "refund_status": customer_return.refund_status,
                    "remarks": customer_return.remarks,
                }, status=status.HTTP_200_OK)


class CustomerRefundReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = (
            CustomerReturnModels.objects
            .values("refund_status")
            .annotate(
                total_cases=Count("id"),
                total_amount=Sum("refund_amount")
            )
        )

        return Response(data)
class CustomerRefundSettlementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        settlements = (
            CustomerReturnModels.objects
            .filter(refund_status="REFUNDED")
            .values("order__id", "product__name")
            .annotate(
                total_qty=Sum("quantity"),
                total_amount=Sum("refund_amount")
            )
        )

        return Response(settlements)
        
class ReturnOrderFullReportView(APIView):

    def get(self, request):

        orders_data = {}

        # =========================
        # 1️⃣ CUSTOMER RETURNS
        # =========================
        customer_returns = CustomerReturnModels.objects.select_related("order", "product")

        for r in customer_returns:
            order = r.order

            if order.id not in orders_data:
                orders_data[order.id] = self.init_order(order)

            data = orders_data[order.id]

            # refund
            data["refund"] += float(r.refund_amount or 0)

            # damage loss
            if r.condition in ["DAMAGED", "LOST"]:
                loss = r.quantity * float(r.product.unit_purchase_price)
                data["damage_loss"] += loss

            data["returns"].append({
                "type": "customer_return",
                "product": r.product.name,
                "sku": r.product.sku,
                "qty": r.quantity,
                "condition": r.condition,
                "refund_amount": float(r.refund_amount or 0),
                "date": r.received_at
            })

        # =========================
        # 2️⃣ COURIER RETURNS
        # =========================
        courier_returns = CourierReturn.objects.select_related("order", "product")

        for r in courier_returns:
            order = r.order

            if order.id not in orders_data:
                orders_data[order.id] = self.init_order(order)

            data = orders_data[order.id]

            # damage loss
            if r.condition == "DAMAGED":
                loss = r.quantity * float(r.product.unit_purchase_price)
                data["damage_loss"] += loss

            # claim
            if r.claim_status == "CLAIMED" and r.claim_result == "RECEIVED":
                data["claim_received"] += float(r.claim_amount or 0)

            data["returns"].append({
                "type": "courier_return",
                "product": r.product.name,
                "sku": r.product.sku,
                "qty": r.quantity,
                "condition": r.condition,
                "claim_amount": float(r.claim_amount or 0),
                "date": r.received_at
            })

        # =========================
        # 3️⃣ ADD ORDER ITEMS
        # =========================
        for order_id, data in orders_data.items():
            order = data["_order_obj"]

            items = order.items.select_related("product")

            for item in items:
                data["items"].append({
                    "product": item.product.name,
                    "sku": item.product.sku,
                    "qty": item.quantity,
                    "unit_price": float(item.unit_price)
                })

        # =========================
        # 4️⃣ FINAL CALCULATION
        # =========================
        final_results = []

        for order_id, data in orders_data.items():

            total_loss = (
                data["refund"]
                + data["damage_loss"]
                - data["claim_received"]
            )

            data["net_loss"] = total_loss
            data["total_loss"] = total_loss

            # cleanup internal field
            del data["_order_obj"]

            final_results.append(data)

        return Response({
            "count": len(final_results),
            "results": final_results
        })


    def init_order(self, order):
        return {
            "_order_obj": order,

            "order_id": order.id,
            "customer_name": order.customer_name,
            "mobile": order.mobile,
            "total_amount": float(order.total_amount),
            "created_at": order.created_at,

            "refund": 0,
            "damage_loss": 0,
            "claim_received": 0,

            "items": [],
            "returns": []
        }
