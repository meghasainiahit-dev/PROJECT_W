from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.db.models import Sum, F, OuterRef, Subquery, IntegerField
from .models import *
from .serializers import *
from .permissions import IsAuthenticatedDelete
from django.db.models import Q
from datetime import datetime, timedelta
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework_simplejwt.tokens import AccessToken
import jwt
import uuid
from datetime import datetime, timedelta
import os
import barcode
from barcode.writer import ImageWriter
from io import BytesIO
from django.conf import settings
from decimal import Decimal

from .inventory_utils import get_order_serials
from .inventory_utils import add_inventory_with_serials 
from django.shortcuts import render
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
import qrcode


def normalized_order_status_history(statuses):
    ordered = sorted(statuses, key=lambda item: item.created_at or datetime.min)
    has_courier_return = any(int(item.status) == 6 for item in ordered)
    has_customer_return = any(int(item.status) == 7 for item in ordered)
    valid = []
    seen = set()

    def has(code):
        return code in seen

    for item in ordered:
        code = int(item.status)
        allowed = False

        if code in {1, 2, 3}:
            allowed = code not in seen and not has(5)
        elif code == 4:
            allowed = has(3) and (has_customer_return or not has_courier_return) and not has(4) and not has(5)
        elif code == 5:
            allowed = not any(has(c) for c in (4, 6, 7, 8, 9))
        elif code == 6:
            allowed = has(3) and not has_customer_return and not has(6) and not has(5)
        elif code == 7:
            allowed = (has(4) or has(3)) and not has(7) and not has(8) and not has(9)
        elif code in {8, 9}:
            allowed = (has(6) or has(7)) and not has(8) and not has(9)

        if allowed:
            valid.append(item)
            seen.add(code)

    return valid


def courier_partner_payloads():
    grouped = {}
    for courier in CourirPartnerModel.objects.prefetch_related("mediators").order_by("id"):
        title = (courier.title or "").strip()
        key = title.casefold()
        if not key:
            continue
        item = grouped.setdefault(key, {"id": courier.id, "title": title, "mediators": [], "_mediator_keys": set()})
        for mediator in courier.mediators.all():
            mediator_title = (mediator.title or "").strip()
            mediator_key = mediator_title.casefold()
            if mediator_key and mediator_key not in item["_mediator_keys"]:
                item["_mediator_keys"].add(mediator_key)
                item["mediators"].append({"id": mediator.id, "title": mediator_title})

    return [
        {"id": item["id"], "title": item["title"], "mediators": item["mediators"]}
        for item in grouped.values()
    ]


def effective_order_status(order):
    status_history = normalized_order_status_history(
        OrderStatus.objects.filter(order_id=order.id)
    )
    return int(status_history[-1].status) if status_history else int(order.order_status)



class VerifyOTPView(APIView):
    permission_classes = []
    def post(self, request):

        # try:
        otp_code = request.data.get('otp')
        # except Exception as e :
        #     return Response({'error':"otp type should be int and 6 digit."},status=400)

        if not otp_code:
            return Response(
                {'error': 'OTP are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )


        if otp_code != "000000":
            return Response({'error': f'Invalid or expired OTP.{otp_code},{type(otp_code)}'}, status=status.HTTP_400_BAD_REQUEST)

        # OTP is valid â€” generate JWT
        # payload = {
        #     "otp":111111,
        #     'otp_verified': True,
        #     'exp': datetime.utcnow() + timedelta(seconds=getattr(settings, 'JWT_EXP_DELTA_SECONDS', 3600)),
        #     'iat': datetime.utcnow(),
        # }

        # token = jwt.encode(payload, getattr(settings, 'JWT_SECRET_KEY', settings.SECRET_KEY), algorithm='HS256')
        
        anonymous_id = str(uuid.uuid4())

        # Create access token manually (no user needed)
        token = AccessToken()
        token.set_exp(lifetime=timedelta(days=7))
        token["anonymous_id"] = anonymous_id
        token["role"] = "anonymous"


        return Response({'token': str(token)}, status=status.HTTP_200_OK)


from decimal import Decimal

from django.db.models import Q, Sum
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from .models import Vendor, Product, PurchaseBill, PurchaseBillItem
from .serializers import VendorSerializer


class VendorListCreateView(APIView):
    #permission_classes = []

    def get(self, request):
        search = request.query_params.get("search", "").strip()

        vendors = Vendor.objects.all().order_by("name")

        if search:
            vendors = vendors.filter(
                Q(name__icontains=search) |
                Q(firm_name__icontains=search) |
                Q(mobile__icontains=search) |
                Q(email__icontains=search) |
                Q(city__icontains=search) |
                Q(state__icontains=search) |
                Q(country__icontains=search) |
                Q(gst_number__icontains=search)
            )

        serializer = VendorSerializer(vendors, many=True)

        return Response({
            "count": vendors.count(),
            "results": serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = VendorSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Vendor created successfully",
                "vendor": serializer.data
            }, status=status.HTTP_201_CREATED)

        return Response({
            "message": "Validation failed",
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class VendorDetailView(APIView):
#permission_classes = []

    def get_object(self, pk):
        return Vendor.objects.filter(pk=pk).first()

    def get(self, request, pk):
        vendor = self.get_object(pk)

        if not vendor:
            return Response({"message": "Vendor not found"}, status=404)

        serializer = VendorSerializer(vendor)
        return Response(serializer.data)

    def put(self, request, pk):
        vendor = self.get_object(pk)

        if not vendor:
            return Response({"message": "Vendor not found"}, status=404)

        serializer = VendorSerializer(vendor, data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Vendor updated successfully",
                "vendor": serializer.data
            })

        return Response({
            "message": "Validation failed",
            "errors": serializer.errors
        }, status=400)

    def patch(self, request, pk):
        vendor = self.get_object(pk)

        if not vendor:
            return Response({"message": "Vendor not found"}, status=404)

        serializer = VendorSerializer(vendor, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Vendor updated successfully",
                "vendor": serializer.data
            })

        return Response({
            "message": "Validation failed",
            "errors": serializer.errors
        }, status=400)

    def delete(self, request, pk):
        vendor = self.get_object(pk)

        if not vendor:
            return Response({"message": "Vendor not found"}, status=404)

        vendor.delete()
        return Response({"message": "Vendor deleted successfully"})


class VendorDashboardView(APIView):
    #permission_classes = []

    def get(self, request, vendor_id):
        vendor = Vendor.objects.filter(id=vendor_id).first()

        if not vendor:
            return Response({"message": "Vendor not found"}, status=404)

        total_bills = PurchaseBill.objects.filter(vendor=vendor).count()

        total_purchase = PurchaseBillItem.objects.filter(
            bill__vendor=vendor
        ).aggregate(total=Sum("quantity"))["total"] or 0

        total_business = PurchaseBill.objects.filter(
            vendor=vendor
        ).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")

        products = []
        products_qs = Product.objects.filter(vendor=vendor).order_by("name")

        for product in products_qs:
            inventory = getattr(product, "inventory", None)

            products.append({
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
                "qty": inventory.quantity if inventory else 0,
                "reminder": getattr(product, "reorder_level", 0),
            })

        return Response({
            "vendor": VendorSerializer(vendor).data,
            "summary": {
                "total_bills": total_bills,
                "total_purchase": total_purchase,
                "total_business": float(total_business),
            },
            "products": products
        })


# -------- Sales Channel-------------------
class SalesChannelListCreateView(APIView):
    permission_classes = []
    
    def get(self, request):
        channels = SalesChannel.objects.all().order_by('name')
        serializer = SalesChannelSerializer(channels, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = SalesChannelSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


class SalesChannelDetailView(APIView):
    def get_object(self, pk):
        return SalesChannel.objects.filter(pk=pk).first()

    def get(self, request, pk):
        channel = self.get_object(pk)
        if not channel:
            return Response({'detail': 'Not found'}, status=404)
        serializer = SalesChannelSerializer(channel)
        return Response(serializer.data)

    def put(self, request, pk):
        channel = self.get_object(pk)
        if not channel:
            return Response({'detail': 'Not found'}, status=404)
        serializer = SalesChannelSerializer(channel, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        channel = self.get_object(pk)
        if not channel:
            return Response({'detail': 'Not found'}, status=404)
        channel.delete()
        return Response(status=204)
 
 
import time
import logging

logger = logging.getLogger("django.request")
# import logging


# logger = logging.getLogger("ticket_app")

# -------- Product ---------------------------------------------
class ProductListCreateView(APIView):
    permission_classes = []

    def get(self, request):
        products = Product.objects.select_related('vendor').order_by('name')
        serializer = ProductSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request):
        serializer = ProductSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)



# Product Delete 

class ProductSelectedDelete(APIView):
    permission_classes = []
    permission_classes = [IsAuthenticatedDelete]
    def delete(self,request,idpk):
        logger.debug("This is a debug log from logger product")
        # pass_key = request.data.get("sec_pass_key")
        
        return Response({"Key Got Access": idpk}, status=201)
        


class ProductDetailView(APIView):
    permission_classes = []
    
    def get_object(self, pk):
        return Product.objects.filter(pk=pk).first()

    def get(self, request, pk):
        product = self.get_object(pk)
        if not product:
            return Response({'detail': 'Not found'}, status=404)
        serializer = ProductSerializer(product)
        return Response(serializer.data)

    def put(self, request, pk):
        product = self.get_object(pk)
        if not product:
            return Response({'detail': 'Not found'}, status=404)
        serializer = ProductSerializer(product, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        product = self.get_object(pk)
        if not product:
            return Response({'detail': 'Not found'}, status=404)
        product.delete()
        return Response(status=204)


class ProductStockView(APIView):
    permission_classes = []
    
    def get(self, request, pk):
        product = Product.objects.filter(pk=pk).first()
        if not product:
            return Response({'detail': 'Not found'}, status=404)

        inv = getattr(product, 'inventory', None)
        current_qty = inv.quantity if inv else 0

        sales = (
            StockMovement.objects
            .filter(product=product, reason='ORDER')
            .values(channel_name=F('channel__name'))
            .annotate(sold=Sum(-F('delta')))
            .order_by('channel_name')           
        )

        return Response({
            'product': ProductSerializer(product).data,
            'current_stock': current_qty,
            'sold_by_channel': list(sales),
        })


# -------- Inventory ------------------------------------ ===============================================
# views.py — replace InventoryListCreateView entirely

class InventoryListCreateView(APIView):
    permission_classes = []

    def get(self, request):
        inventory = Inventory.objects.select_related('product', 'product__vendor').all().order_by('product__name')
        serializer = InventorySerializer(inventory, many=True)
        return Response(serializer.data)

    def post(self, request):
        product_id = request.data.get("product")
        quantity   = request.data.get("quantity")

        if not product_id or quantity is None:
            return Response({"detail": "product and quantity are required"}, status=400)

        try:
            quantity = int(quantity)
        except (ValueError, TypeError):
            return Response({"detail": "quantity must be an integer"}, status=400)

        if quantity <= 0:
            return Response({"detail": "quantity must be greater than 0"}, status=400)

        product = Product.objects.filter(id=product_id).first()
        if not product:
            return Response({"detail": "Product not found"}, status=404)

        # ── generate serials + update inventory atomically ─────────────────
        serials = add_inventory_with_serials(product, quantity)

        # ── log stock movement ─────────────────────────────────────────────
        StockMovement.objects.create(
            product=product,
            delta=quantity,
            reason='ADJUST',
            note=f"Inventory added via API. Serials: {serials[0]} to {serials[-1]}"
        )

        inv = Inventory.objects.get(product=product)
        return Response({
            "product":      product_id,
            "quantity":     inv.quantity,
            "serials_from": serials[0],
            "serials_to":   serials[-1],
            "serials":      serials,
        }, status=201)
    # ============================================================================================
# class InventoryListCreateView(APIView):
#     permission_classes = []
    
#     def get(self, request):
#         inventory = Inventory.objects.select_related('product', 'product__vendor').all().order_by('product__name')
#         serializer = InventorySerializer(inventory, many=True)
#         return Response(serializer.data)

#     def post(self, request):
#         serializer = InventorySerializer(data=request.data)
#         if serializer.is_valid():
#             serializer.save()
#             return Response(serializer.data, status=201)
#         return Response(serializer.errors, status=400)


class InventoryDetailView(APIView):
    permission_classes = []
    
    def get(self, request, pk):
        inv = Inventory.objects.filter(pk=pk).first()
        if not inv:
            return Response({'detail': 'Not found'}, status=404)
        serializer = InventorySerializer(inv)
        return Response(serializer.data)


class InventoryAdjustView(APIView):
    permission_classes = []

    def post(self, request):
        sku   = request.data.get('sku')
        reason = request.data.get('reason', 'ADJUST')
        note   = request.data.get('note', '')
        valid_reasons = {choice[0] for choice in StockMovement.REASON_CHOICES}

        try:
            delta = int(request.data.get('delta', 0))
        except (ValueError, TypeError):
            return Response({'detail': 'delta must be integer'}, status=400)

        if not sku or delta == 0:
            return Response({'detail': 'sku and non-zero delta required'}, status=400)

        if reason not in valid_reasons:
            return Response({'detail': 'Invalid reason for adjustment'}, status=400)

        product = Product.objects.filter(sku=sku).first()
        if not product:
            return Response({'detail': 'Invalid SKU'}, status=400)

        if delta > 0:
            # ── ADD stock: create serial units ────────────────────────────
            serials = add_inventory_with_serials(product, delta, note)
            inv     = Inventory.objects.get(product=product)
            StockMovement.objects.create(
                product=product, delta=delta, reason=reason, note=note
            )
            return Response({
                'sku':          sku,
                'new_quantity': inv.quantity,
                'serials_added': serials,
            })
        else:
            # ── REMOVE stock (manual adjustment / write-off) ──────────────
            abs_delta = abs(delta)
            from django.db import transaction
            with transaction.atomic():
                inv, _ = Inventory.objects.select_for_update().get_or_create(
                    product=product, defaults={'quantity': 0}
                )
                if inv.quantity < abs_delta:
                    return Response({
                        'detail': f'Cannot reduce below zero. Available quantity is {inv.quantity}.'
                    }, status=400)

                units = list(
                    ProductUnit.objects
                    .select_for_update()
                    .filter(product=product, status='in_stock')
                    .order_by('serial_number')[:abs_delta]
                )
                if len(units) < abs_delta:
                    return Response({'detail': 'Available serial stock is less than the requested reduction.'}, status=400)

                ProductUnit.objects.filter(id__in=[u.id for u in units]).update(status='damaged')
                inv.quantity -= abs_delta
                inv.save(update_fields=['quantity'])

            StockMovement.objects.create(
                product=product, delta=delta, reason=reason, note=note
            )
            return Response({'sku': sku, 'new_quantity': inv.quantity})


# class InventoryAdjustView(APIView):
#     permission_classes = []
    
#     def post(self, request):
#         sku = request.data.get('sku')
#         try:
#             delta = int(request.data.get('delta', 0))
#         except ValueError:
#             return Response({'detail': 'delta must be integer'}, status=400)

#         reason = request.data.get('reason', 'ADJUST')
#         note = request.data.get('note', '')

#         if not sku or delta == 0:
#             return Response({'detail': 'sku and non-zero delta required'}, status=400)

#         product = Product.objects.filter(sku=sku).first()
#         if not product:
#             return Response({'detail': 'Invalid SKU'}, status=400)

#         inv, _ = Inventory.objects.get_or_create(product=product, defaults={'quantity': 0})
#         new_qty = inv.quantity + delta
#         if new_qty < 0:
#             return Response({'detail': f'Cannot reduce below zero. Current {inv.quantity}, delta {delta}'}, status=400)
#         inv.quantity = new_qty
#         inv.save()

#         StockMovement.objects.create(product=product, delta=delta, reason=reason, note=note)
#         return Response({'sku': sku, 'new_quantity': inv.quantity}) 


    
    
class OrderListCreateView(APIView):
    permission_classes = []

    def get(self, request):
        status_filter = request.query_params.get("status", "ALL")
        search = request.query_params.get("search", "").strip()

        orders = (
            Order.objects
            .filter(is_deleted=False)
            .select_related("channel")
            .prefetch_related(
                "items__product",
                "remarks_list",
                "shipments",              # ✅ Bug 1 fixed
            )
            .order_by("-id")
        )

        STATUS_QUERY_MAP = {
            "IN_PROCESS": 1, "PACKED": 2, "IN_TRANSIT": 3,
            "DELIVERED": 4, "CANCELLED": 5, "COURIER_RETURN": 6,
            "CUSTOMER_RETURN": 7, "RETURNED": 8,
        }

        if status_filter and status_filter.upper() != "ALL":
            sf = status_filter.upper()
            if sf == "COURIER_RETURN":    # ✅ Bug 2 fixed — entire chain indented in
                order_ids = CourierReturn.objects.values_list("order_id", flat=True).distinct()
                orders = orders.filter(id__in=order_ids)
            elif sf == "CUSTOMER_RETURN":
                order_ids = CustomerReturnModels.objects.values_list("order_id", flat=True).distinct()
                orders = orders.filter(id__in=order_ids)
            elif sf == "RETURNED":
                courier_ids = CourierReturn.objects.values_list("order_id", flat=True)
                customer_ids = CustomerReturnModels.objects.values_list("order_id", flat=True)
                orders = orders.filter(id__in=set(list(courier_ids) + list(customer_ids)))
            elif sf == "RECEIVED":
                order_ids = CourierReturn.objects.filter(
                    return_status="APPROVED"
                ).values_list("order_id", flat=True).distinct()
                orders = orders.filter(id__in=order_ids)
            else:
                status_code = STATUS_QUERY_MAP.get(sf)
                if status_code:
                    orders = orders.filter(order_status=status_code)

        if search:
            search_filter = (
                Q(customer_name__icontains=search) |
                Q(channel_order_id__icontains=search) |
                Q(channel__name__icontains=search)
            )
            if search.isdigit():                       # ✅ Bug 3 fixed
                search_filter |= Q(id=int(search))
            orders = orders.filter(search_filter)      # ✅ Bug 3 fixed

        orders = orders.distinct()
        orders_list = list(orders)

        order_ids = [o.id for o in orders_list]
        all_statuses = (
            OrderStatus.objects                        # ✅ Bug 4 fixed
            .filter(order_id__in=order_ids)
            .order_by("order_id", "-created_at")
        )

        latest_status_map = {}
        for s in all_statuses:
            if s.order_id not in latest_status_map:
                latest_status_map[s.order_id] = s

        for order in orders_list:
            statuses = latest_status_map.get(order.id)
            order._prefetched_statuses = [statuses] if statuses else []

        serializer = OrderListSerializer(orders_list, many=True)

        return Response({
            "data": serializer.data,
            "count": len(orders_list)
        })  
    def post(self, request):
        serializer = OrderCreateSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        try:
            order = serializer.save()

            allocated = []
            for item in order.items.select_related("product"):
                assigned_serials = list(
                    ProductUnit.objects.filter(
                        product=item.product,
                        order=order,
                        status="sold"
                    ).values_list("serial_number", flat=True)
                )

                allocated.append({
                    "product_id": item.product.id,
                    "product_name": item.product.name,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                    "serials": assigned_serials,
                })

            OrderStatus.objects.create(
                order_id=order.id,
                status=1,
                json={"note": "In Process"}
            )

            return Response({
                "message": "Order created successfully",
                "order_id": order.id,
                "total_amount": str(order.total_amount),
                "package_expence": str(order.package_expence),
                "buyer_shipment_charger": str(order.buyer_shipment_charger),
                "buyer_tax_amount": str(order.buyer_tax_amount),
                "paid_amount": str(order.paid_amount),
                "remaining_amount": str(order.remaining_amount()),
                "payment_status": order.paid_status,
                "order": OrderSerializer(order).data,
                "remarks": OrderRemarkSerializer(order.remarks_list.all(), many=True).data,
                "allocated_serials": allocated,
            }, status=201)

        except Exception as e:
            return Response({
                "error": "Something went wrong",
                "details": str(e)
            }, status=500)
class AddOrderRemarkView(APIView):
    permission_classes = []

    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)
        remark = request.data.get("remark")

        if not remark:
            return Response({"error": "Remark is required"}, status=400)

        obj = OrderRemark.objects.create(
            order=order,
            remark=remark
        )

        return Response({
            "message": "Remark added successfully",
            "data": OrderRemarkSerializer(obj).data
        })
def generate_barcodes_for_quantity(product, qty, request=None):
    last_serial = product.serial or 0
    barcodes = []

    qrcodes_dir = os.path.join(settings.MEDIA_ROOT, "qrcodes")
    os.makedirs(qrcodes_dir, exist_ok=True)

    for i in range(qty):
        new_serial = last_serial + i + 1
        serial_code = str(new_serial).zfill(5)

        full_barcode = f"{product.sku}-{serial_code}"

        qr = qrcode.make(full_barcode)

        file_name = f"{full_barcode}.png"
        file_path = os.path.join(qrcodes_dir, file_name)

        qr.save(file_path)

        image_url = (
            request.build_absolute_uri(f"{settings.MEDIA_URL}qrcodes/{file_name}")
            if request else
            f"{settings.MEDIA_URL}qrcodes/{file_name}"
        )

        barcodes.append({
            "barcode": full_barcode,
            "image": image_url,
            "qr_image": image_url,
        })

    product.serial = last_serial + qty
    product.save(update_fields=["serial"])

    return barcodes
# # ======================================================================================================
# # class OrderDetailView(APIView):
# #     permission_classes = []

# #     def get(self, request, pk):
# #         order = get_object_or_404(Order, pk=pk)
# #         items_data = []

# #         for item in order.items.select_related(
# #             "product", "product__inventory", "product__vendor"
# #         ):
# #             product       = item.product
# #             inventory_qty = product.inventory.quantity if hasattr(product, "inventory") else 0

# #             # ── serials jo is order mein assign hue hain ─────────────────
# #             units = (
# #                 ProductUnit.objects
# #                 .filter(product=product, order=order, status="sold")
# #                 .order_by("serial_number")
# #             )

# #             # ── har serial ke liye barcode image generate/return karo ─────
# #             barcodes_dir = os.path.join(settings.MEDIA_ROOT, "barcodes")
# #             os.makedirs(barcodes_dir, exist_ok=True)

# #             serials_with_images = []
# #             for unit in units:
# #                 file_name = f"{unit.serial_number}.png"
# #                 file_path = os.path.join(barcodes_dir, file_name)

# #                 if not os.path.exists(file_path):
# #                     import barcode as barcode_lib
# #                     from barcode.writer import ImageWriter
# #                     from io import BytesIO
# #                     code128 = barcode_lib.get("code128", unit.serial_number, writer=ImageWriter())
# #                     buffer  = BytesIO()
# #                     code128.write(buffer)
# #                     with open(file_path, "wb") as f:
# #                         f.write(buffer.getvalue())

# #                 image_url = request.build_absolute_uri(
# #                     f"{settings.MEDIA_URL}barcodes/{file_name}"
# #                 )
# #                 serials_with_images.append({
# #                     "serial_number": unit.serial_number,
# #                     "barcode_image": image_url,
# #                 })

# #             # ── product_image_variants mein absolute URLs banana ──────────
# #             variant_images = []
# #             for img_url in (product.product_image_variants or []):
# #                 if img_url:
# #                     # Agar relative path hai to absolute banao
# #                     if img_url.startswith("http"):
# #                         variant_images.append(img_url)
# #                     else:
# #                         variant_images.append(request.build_absolute_uri(img_url))
# #                 else:
# #                     variant_images.append(None)

# #             items_data.append({
# #                 # ── Product basic info ────────────────────────────────────
# #                 "product_id":        product.id,
# #                 "product_name":      product.name,
# #                 "product_sku":       product.sku,
# #                 "product_barcode":   product.barcode,
# #                 "product_barcode_image": (
# #                     request.build_absolute_uri(product.barcode_image.url)
# #                     if product.barcode_image else None
# #                 ),

# #                 # ── 🆕 Product images ─────────────────────────────────────
# #                 "product_image": (
# #                     request.build_absolute_uri(product.product_image.url)
# #                     if product.product_image else None
# #                 ),
# #                 "product_image_variants": variant_images,

# #                 # ── 🆕 Vendor info ────────────────────────────────────────
# #                 "vendor_id":         product.vendor.id,
# #                 "vendor_name":       product.vendor.name,

# #                 # ── Order item info ───────────────────────────────────────
# #                 "ordered_quantity":  item.quantity,
# #                 "unit_price":        item.unit_price,
# #                 "total_price":       float(item.unit_price) * item.quantity,

# #                 # ── Stock info ────────────────────────────────────────────
# #                 "stock_left":        inventory_qty,

# #                 # ── Serials + images assigned to this order ───────────────
# #                 "serials":           serials_with_images,
# #             })

# #         return Response({
# #             # ── Order basic info ──────────────────────────────────────────
# #             "order_id":        order.id,
# #             "channel":         order.channel.name,
# #             "channel_order_id": order.channel_order_id,
# #             "customer_name":   order.customer_name,
# #             "customer_email":  order.customer_email,
# #             "mobile":          order.mobile,
# #             "country_code":    order.country_code,
# #             "remarks": [
# #                 {
# #                   "remark": r.remark,
# #                   "created_at": r.created_at
# #                 }
# #                 for r in order.remarks_list.all()
# #             ],
# #             "created_at":      order.created_at,

# #             # ── Payment info ──────────────────────────────────────────────
# #             "paid_status":     order.paid_status,
# #             "payment_method":  order.payment_method,
# #             "payment_date":    order.payment_date,
# #             "transaction_id":  order.transaction_id,

# #             # ── Items ─────────────────────────────────────────────────────
# #             "total_items":     sum(i["ordered_quantity"] for i in items_data),
# #             "items":           items_data,
# #         }, status=200)


class OrderDetailView(APIView):
    permission_classes = []

    def get(self, request, pk):
        order = get_object_or_404(
            Order.objects.select_related("channel")
            .prefetch_related(
                "items__product",
                "items__product__vendor",
                "remarks_list",
                "shipments__courier_partner",
                "shipments__mediator",
            ),
            pk=pk,
        )

        latest_status = (
            OrderStatus.objects
            .filter(order_id=order.id)
            .order_by("-created_at")
            .first()
        )

        status_code = latest_status.status if latest_status else order.order_status

        if getattr(order, "status", "") == "CANCELLED":
            status_text = "Cancelled"
        else:
            status_text = ORDER_STATUS_MAP.get(status_code, "Active")

        items_data = []

        for item in order.items.select_related("product", "product__vendor"):
            product = item.product

            if not product:
                continue

            inventory_qty = 0
            if hasattr(product, "inventory") and product.inventory:
                inventory_qty = product.inventory.quantity

            units = (
                ProductUnit.objects
                .filter(product=product, order=order, status="sold")
                .order_by("serial_number")
            )

            serials_with_images = []

            qrcodes_dir = os.path.join(settings.MEDIA_ROOT, "qrcodes")
            os.makedirs(qrcodes_dir, exist_ok=True)

            for unit in units:
                file_name = f"{unit.serial_number}.png"
                file_path = os.path.join(qrcodes_dir, file_name)

                if not os.path.exists(file_path):
                    qr = qrcode.make(unit.serial_number)
                    qr.save(file_path)

                qr_image = request.build_absolute_uri(
                    f"{settings.MEDIA_URL}qrcodes/{file_name}"
                )

                serials_with_images.append({
                    "serial_number": unit.serial_number,
                    "qr_image": qr_image,
                    "barcode_image": qr_image,
                    "qr_value": unit.serial_number,
                })

            product_image = ""
            if product.product_image:
                product_image = request.build_absolute_uri(product.product_image.url)

            variant_images = []
            for img in product.product_image_variants or []:
                if not img:
                    continue

                if str(img).startswith("http"):
                    variant_images.append(img)
                else:
                    variant_images.append(request.build_absolute_uri(str(img)))

            unit_price = Decimal(str(item.unit_price or 0))
            quantity = item.quantity or 0
            total_price = unit_price * quantity

            items_data.append({
                "id": item.id,
                "product_id": product.id,
                "name": product.name,
                "product_name": product.name,
                "sku": product.sku,
                "product_sku": product.sku,

                "product_barcode": getattr(product, "barcode", "") or product.sku,
                "product_barcode_image": (
                    request.build_absolute_uri(product.barcode_image.url)
                    if getattr(product, "barcode_image", None)
                    else ""
                ),

                "image": product_image,
                "product_image": product_image,
                "product_image_variants": variant_images,

                "vendor_id": product.vendor.id if product.vendor else "",
                "vendor_name": product.vendor.name if product.vendor else "",

                "quantity": quantity,
                "ordered_quantity": quantity,
                "unit_price": float(unit_price),
                "subtotal": float(total_price),
                "total_price": float(total_price),

                "stock_left": inventory_qty,
                "serial": serials_with_images[0]["serial_number"] if serials_with_images else "",
                "serials": serials_with_images,
            })

        remarks_qs = order.remarks_list.order_by("-created_at")
        latest_remark = remarks_qs.first()

        first_item = order.items.select_related("product").first()
        package_product = first_item.product if first_item else None

        shipment = (
            order.shipments
            .select_related("courier_partner", "mediator")
            .order_by("-id")
            .first()
        )

        items_total = sum(
            Decimal(str(item["total_price"]))
            for item in items_data
        )

        product_tax_percent = Decimal("5.00")
        product_tax = (items_total * product_tax_percent / Decimal("100")).quantize(Decimal("0.01"))
        package_expence = Decimal(str(order.package_expence or 0))
        buyer_shipping = Decimal(str(order.buyer_shipment_charger or 0))
        buyer_tax = Decimal(str(order.buyer_tax_amount or 0))
        calculated_total = (
            items_total
            + product_tax
            + package_expence
            + buyer_shipping
            + buyer_tax
        ).quantize(Decimal("0.01"))
        grand_total = Decimal(str(order.total_amount or items_total))
        other_adjustment = (grand_total - calculated_total).quantize(Decimal("0.01"))

        return Response({
            "id": order.id,
            "order_id": order.id,
            "date": order.created_at.date().isoformat() if order.created_at else "",
            "created_at": order.created_at,

            "channel": order.channel.name if order.channel else "",
            "channel_name": order.channel.name if order.channel else "",
            "channel_order_id": order.channel_order_id or "",
            "channel_id": order.channel_order_id or "",

            "customer_name": order.customer_name or "",
            "customer_email": order.customer_email or "",
            "email": order.customer_email or "",
            "mobile": order.mobile or "",
            "country_code": order.country_code or "",

            "order_status": status_code,
            "status": status_text,
            "status_date": (
                latest_status.created_at.strftime("%d/%m/%Y - %H:%M")
                if latest_status and latest_status.created_at
                else ""
            ),
            "status_timestamp": (
                latest_status.created_at.isoformat()
                if latest_status and latest_status.created_at
                else ""
            ),

            "remarks": [
                {
                    "id": remark.id,
                    "remark": remark.remark,
                    "created_at": (
                        remark.created_at.strftime("%d %b %Y, %I:%M %p")
                        if remark.created_at
                        else ""
                    ),
                }
                for remark in remarks_qs
            ],
            "remark_date": (
                latest_remark.created_at.strftime("%d %b %Y, %I:%M %p")
                if latest_remark and latest_remark.created_at
                else ""
            ),

            "paid_status": order.paid_status,
            "paid_amount": float(order.paid_amount or 0),
            "remaining_amount": float(order.remaining_amount()),
            "payment_method": order.payment_method,
            "payment_date": order.payment_date,
            "transaction_id": order.transaction_id,
            "bill_generated": bool(
                order.payment_date
                or order.payment_method
                or order.transaction_id
                or order.paid_amount > Decimal("0.00")
            ),

            "total_items": sum(item["ordered_quantity"] for item in items_data),
            "total_amount": float(grand_total),
            "package_expence": float(order.package_expence or 0),
            "buyer_shipment_charger": float(order.buyer_shipment_charger or 0),
            "buyer_tax_amount": float(order.buyer_tax_amount or 0),

            "items": items_data,

            "bill_breakdown": {
                "items_total": float(items_total),
                "product_tax_percent": float(product_tax_percent),
                "product_tax": float(product_tax),
                "package_expence": float(package_expence),
                "buyer_shipment_charger": float(buyer_shipping),
                "buyer_tax_amount": float(buyer_tax),
                "calculated_total": float(calculated_total),
                "other_adjustment": float(other_adjustment),
                "printed_amount": float(grand_total),
                "grand_total": float(grand_total),
            },

            "package": {
                "height": getattr(package_product, "height", "") or "",
                "width": getattr(package_product, "width", "") or "",
                "length": getattr(package_product, "length", "") or "",
                "dead_weight": getattr(package_product, "weight_before", "") or "",
                "vol_weight": getattr(package_product, "weight_after", "") or "",
                "billed_weight": (
                    getattr(package_product, "weight_after", None)
                    or getattr(package_product, "weight_before", "")
                    or ""
                ),
            } if package_product else {},

            "shipment": {
                "courier": shipment.courier_partner.title if shipment and shipment.courier_partner else "",
                "mediator": shipment.mediator.title if shipment and shipment.mediator else "",
                "tracking_id": shipment.tracking_id if shipment else "",
                "ship_date": (
                    shipment.shipping_date.strftime("%d %b %Y")
                    if shipment and shipment.shipping_date
                    else ""
                ),
                "shipping_expense": float(shipment.shipping_expense or 0) if shipment else 0,
                "tracking_url": shipment.tracking_url if shipment else "",
            } if shipment else {},
        })

class ProductDeleteSafeView(APIView):
    permission_classes = []

    def delete(self, request, pk):
        product = Product.objects.filter(pk=pk).first()
        if not product:
            return Response({"error": "Product not found"}, status=404)

        try:
            product.delete()
            return Response({
                "message": "Product deleted successfully"
            }, status=200)

        except ProtectedError:
            return Response({
                "error": "Cannot delete product. It is used in orders/inventory."
            }, status=400)

        except Exception as e:
            return Response({
                "error": "Something went wrong",
                "details": str(e)
            }, status=500)
# =========================================================================================================
# class OrderDetailView(APIView):
#     permission_classes = []

#     def get(self, request, pk):
#         order = get_object_or_404(Order, pk=pk)

#         items_data = []

#         for item in order.items.select_related("product", "product__inventory"):
#             product = item.product
#             inventory_qty = product.inventory.quantity if hasattr(product, "inventory") else 0

#             # ðŸŽ¯ generate barcodes based on order quantity
#             barcodes = generate_barcodes_for_quantity(
#                 product=product,
#                 qty=item.quantity,
#                 request=request
#             )

#             items_data.append({
#                 "product_id": product.id,
#                 "product_name": product.name,
#                 "sku": product.sku,
#                 "ordered_quantity": item.quantity,
#                 "unit_price": item.unit_price,
#                 "stock_left": inventory_qty,
#                 "barcodes": barcodes
#             })

#         return Response({
#             "order_id": order.id,
#             "customer_name": order.customer_name,
#             "customer_email": order.customer_email,
#             "created_at": order.created_at,
#             "items": items_data
#         }, status=status.HTTP_200_OK)


 
# -------- Reports -----------------------------------------
class SalesByChannelView(APIView):
    permission_classes = []
    
    def get(self, request):
        data = (
            StockMovement.objects
            .filter(reason='ORDER')
            .values('channel__name')
            .annotate(total_items=Sum(-F('delta')))
            .order_by('channel__name')
        )
        return Response(list(data))


class ProductSummaryView(APIView):
    permission_classes = []
    
    def get(self, request):
        inv = Inventory.objects.filter(product=OuterRef('pk')).values('quantity')
        sold = (
            StockMovement.objects
            .filter(product=OuterRef('pk'), reason='ORDER')
            .values('product')
            .annotate(total=Sum(-F('delta')))
            .values('total')
        )

        qs = (
            Product.objects
            .all()
            .annotate(
                current_stock=Subquery(inv[:1], output_field=IntegerField()),
                total_sold=Subquery(sold[:1], output_field=IntegerField()),
            )
            .values('id', 'name', 'sku', 'barcode', 'current_stock', 'total_sold')
        )

        result = []
        for row in qs:
            row['current_stock'] = row['current_stock'] or 0
            row['total_sold'] = row['total_sold'] or 0
            result.append(row)
        return Response(result)
    
class StockFilterAPIView(APIView):
    permission_classes = []
    """
    Example: /api/stock-filter/?vendor_id=1&color=Red&size=M&material=Leather
    """
    def get(self, request):
        filters = {}
        if request.query_params.get("vendor_id"):
            filters["vendor_id"] = request.query_params.get("vendor_id")
        if request.query_params.get("name"):
            filters["name__icontains"] = request.query_params.get("name")
        if request.query_params.get("color"):
            filters["color__iexact"] = request.query_params.get("color")
        if request.query_params.get("size"):
            filters["size__iexact"] = request.query_params.get("size")
        if request.query_params.get("material"):
            filters["material__iexact"] = request.query_params.get("material")

        products = Product.objects.filter(**filters)
        total_stock = Inventory.objects.filter(product__in=products).aggregate(total=Sum("quantity"))["total"] or 0
        return Response({"total_stock": total_stock})



# from rest_framework.views import APIView
# from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from .serializers import ReturnSerializer


class WPSReturnAPIView(APIView):
    permission_classes = []
    
    def post(self, request):
        logger.debug("This is a debug log from logger product")
        serializer = ReturnSerializer(data=request.data)
        if serializer.is_valid():
            product = get_object_or_404(Product, id=serializer.validated_data["product_id"])
            quantity = serializer.validated_data["quantity"]
            condition = serializer.validated_data["condition"]
            channel_id = get_object_or_404(Product, id=serializer.validated_data["channel_id"])
            order = get_object_or_404(Order, id=serializer.validated_data["order_id"])

            # Movement log
            StockMovement.objects.create(
                product=product,
                delta=+quantity if condition == "OK" else 0,
                reason="WPS",
                condition=condition,
                channel_id = channel_id.id,
                order_id = order.id
            )
            
            # Order Data Update
            
            orderItem = OrderItem.objects.get(order = order)
            orderItem.quantity -= quantity
            orderItem.save()
            
            if condition == "OK":
                inv, _ = Inventory.objects.get_or_create(product=product)
                inv.quantity += quantity
                inv.save()
            else:
                dmg, _ = DamageInventory.objects.get_or_create(product=product)
                dmg.quantity += quantity
                dmg.save()

            return Response({"message": "WPS Return processed"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




class CustomerReturnAPIView(APIView):
    permission_classes = []
    
    def post(self, request):
        logger.debug("This is a debug log from logger product")
        serializer = ReturnSerializer(data=request.data)
        if serializer.is_valid():
            order = get_object_or_404(Order, id=serializer.validated_data["order_id"])
            product = get_object_or_404(Product, id=serializer.validated_data["product_id"])
            quantity = serializer.validated_data["quantity"]
            condition = serializer.validated_data["condition"]
            channel_id = get_object_or_404(Product, id=serializer.validated_data["channel_id"])

            # Movement log
            StockMovement.objects.create(
                product=product,
                delta=+quantity if condition == "OK" else 0,
                reason="RETURN",
                condition=condition,
                channel_id = channel_id.id,
                order=order,
            )
            
            orderItem = OrderItem.objects.get(order = order)
            orderItem.quantity -= quantity
            orderItem.save()

            if condition == "OK":
                inv, _ = Inventory.objects.get_or_create(product=product)
                inv.quantity += quantity
                inv.save()
            else:
                dmg, _ = DamageInventory.objects.get_or_create(product=product)
                dmg.quantity += quantity
                dmg.save()

            return Response({"message": "Customer Return processed"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        

        
class LowStocksAlterts(APIView):
    permission_classes = []
    
    def get(self,request):
        logger.debug("This is a debug log from logger low stock")
        
        # Low Product
        
        products = Product.objects.all()
        # products_low = pro.filter(inventory__quantity__lte = 20).values("name","sku","inventory__quantity")
        
        serialize = ProductStockSerializer(products , many =True)
        total_Stock = 0
        low_count = 0
        total_stock_value = 0.0
        low_products = []
        for pro in serialize.data:
            if pro['inventory_quantity'] <= 20 or (not pro['inventory_quantity']):
                low_products.append(pro)
                if pro['inventory_quantity']:
                    low_count += pro['inventory_quantity']
                    total_Stock += pro['inventory_quantity']
                    total_stock_value += float(pro['unit_purchase_price'])*pro['inventory_quantity']
            else :
                total_Stock += pro['inventory_quantity']
                total_stock_value += float(pro['unit_purchase_price'])*pro['inventory_quantity']
                
        
        # for pro in products:
            
        #     pro.filter(inventory__quantity__lte = 20)
        
        # products_low = Product.objects.filter(inventory__quantity__lte=20).values("name","sku","inventory__quantity")
        # total_low_count = products_low.count()
        
        return Response({"message":"Data Got","data": {
            "Stock_detail":serialize.data,
            "Stock_count":total_Stock,
            "total_stock_value":total_stock_value,
            "low_products":low_products,
            "low_count":low_count
        }, "status" : 200})
        
class ReturnDataHistory(APIView):
    permission_classes = []
    
    def get(self,request):
        logger.debug("This is a debug log from logger Return History")
        reson = request.query_params.get("reason")
        condition = request.query_params.get("condition")
        filters = Q()
        if reson:
            if reson in ["ORDER","PURCHASE","RETURN","WPS","ADJUST"]:
                filters = Q(reason = reson)
            else:
                return Response({"message":"Please Choose right option.","status":400})
        elif condition :
            if condition in ["OK","DAMAGED"]:
                filters= Q(condition = condition)
            else :
                return Response({"message":"Please Choose right option.","status":400})
        
        return_history = StockMovement.objects.filter(filters)
        serializer = StockMovementSerializer(return_history , many = True)
        
        return Response({"message":"Result Fetched Successfully.", "data":serializer.data , "status":200})
        
class ProductUpdateAPIView(APIView):
    permission_classes = []

    def get_object(self, pk):
        return Product.objects.select_related('vendor').filter(pk=pk).first()

    def get(self, request, pk):
        product = self.get_object(pk)
        if not product:
            return Response({"error": "Product not found"}, status=404)
        
        product_data = ProductSerializer(product, context={'request': request}).data
        
        return Response({
            **product_data,
            "variants": []
        })

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def _update(self, request, pk, partial):
        product = self.get_object(pk)
        if not product:
            return Response({"error": "Product not found"}, status=404)

        serializer = ProductSerializer(
            product,
            data=request.data,
            partial=partial,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)


class ProductDeleteAPIView(APIView):
    permission_classes = []

    def delete(self, request, pk):
        product = Product.objects.filter(pk=pk).first()
        if not product:
            return Response({"error": "Not found"}, status=404)
        
        # Variants bhi automatically delete honge (CASCADE)
        product.delete()
        return Response({"message": "Deleted"}, status=204)
import random
import string
        
class ImageUploadAPIView(APIView):
    def post(self, request):
        file = request.FILES.get('image')

        if not file:
            return Response({"error": "No image provided"}, status=400)

        # 👉 get extension (.jpg, .png)
        ext = os.path.splitext(file.name)[1]

        # 👉 random string (a-z + 1-9)
        random_name = ''.join(random.choices(string.ascii_lowercase + "123456789", k=20))

        filename = f"{random_name}{ext}"

        # 👉 save in products folder
        file_path = f'products/{filename}'

        saved_path = default_storage.save(file_path, file)

        return Response({
            "path": settings.MEDIA_URL + saved_path
        })
        
        
class OrderSoftDeleteView(APIView):
    permission_classes = []

    def delete(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)

        if order.is_deleted:
            return Response({
                "message": "Order already deleted"
            }, status=400)

        order.is_deleted = True
        order.save()

        return Response({
            "message": f"Order {order.id} soft deleted successfully"
        })
        
class CancelOrderView(APIView):
    permission_classes = []

    def post(self, request, order_id):

        order = get_object_or_404(Order, id=order_id)

        # ❌ already cancelled
        if order.status == "CANCELLED":
            return Response({"message": "Order already cancelled"}, status=400)

        # ❌ agar return aa chuka hai to cancel mat hone do
        has_returns = (
            order.customer_returns.exists() or
            order.courierreturn_set.exists()
        )

        if has_returns:
            return Response({
                "message": "Cannot cancel order. Returns already processed."
            }, status=400)

        with transaction.atomic():

            # 1️⃣ Order items
            items = order.items.select_related("product")

            for item in items:
                product = item.product
                qty = item.quantity

                # 2️⃣ ProductUnit reset (sold → in_stock)
                units = ProductUnit.objects.filter(
                    product=product,
                    order=order,
                    status="sold"
                )[:qty]

                unit_ids = [u.id for u in units]

                ProductUnit.objects.filter(id__in=unit_ids).update(
                    status="in_stock",
                    order=None
                )

                # 3️⃣ Inventory update
                inv, _ = Inventory.objects.get_or_create(product=product)
                inv.quantity += qty
                inv.save()

                # 4️⃣ Stock movement log
                StockMovement.objects.create(
                    product=product,
                    delta=qty,
                    reason="RETURN",
                    condition="OK",
                    note=f"Order cancelled #{order.id}"
                )

            # 5️⃣ Order status update
            order.status = "CANCELLED"
            order.save()

        return Response({
            "message": f"Order {order.id} cancelled successfully"
        })
        
class CourirPartnerCreateAPIView(APIView):
    def post(self, request):
        serializer = CourirPartnerSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Courier Partner Created Successfully",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        


class CourirPartnerListAPIView(APIView):
    def get(self, request):
        return Response(courier_partner_payloads())


class CourirPartnerDetailAPIView(APIView):
    permission_classes = []

    def put(self, request, pk):
        courier = get_object_or_404(CourirPartnerModel, id=pk)
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "Courier name is required."}, status=status.HTTP_400_BAD_REQUEST)

        duplicate = CourirPartnerModel.objects.filter(title__iexact=title).exclude(id=courier.id).order_by("id").first()
        if duplicate:
            return Response({"message": "Courier partner with this name already exists."}, status=status.HTTP_400_BAD_REQUEST)

        courier.title = title
        courier.save(update_fields=["title"])

        mediator_titles = []
        seen = set()
        for mediator in request.data.get("mediators", []):
            mediator_title = (mediator.get("title") or "").strip()
            mediator_key = mediator_title.casefold()
            if mediator_title and mediator_key not in seen:
                seen.add(mediator_key)
                mediator_titles.append(mediator_title)

        existing = list(courier.mediators.all())
        used_mediator_ids = []
        for mediator_title in mediator_titles:
            current = next((m for m in existing if (m.title or "").strip().casefold() == mediator_title.casefold()), None)
            if current:
                if current.title != mediator_title:
                    current.title = mediator_title
                    current.save(update_fields=["title"])
            else:
                current = MediatorModels.objects.create(courier_partner=courier, title=mediator_title)
            used_mediator_ids.append(current.id)

        courier.mediators.exclude(id__in=used_mediator_ids).delete()
        return Response({"message": "Courier partner updated successfully.", "data": courier_partner_payloads()})

    def delete(self, request, pk):
        courier = get_object_or_404(CourirPartnerModel, id=pk)
        if courier.shipments.exists():
            return Response(
                {"message": "Is courier partner par shipments linked hain, delete nahi kar sakte."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        courier.delete()
        return Response({"message": "Courier partner deleted successfully."})
        
class CreateShipmentFromOrderAPIView(APIView):
    def post(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return Response({"error": "Order not found"}, status=404)

        data = request.data.copy()
        data["order"] = order.id

        serializer = ShipmentSerializer(data=data)
        if serializer.is_valid():
            serializer.save(order=order)
            return Response({
                "message": "Shipment Created for Order",
                "data": serializer.data
            }, status=201)

        return Response(serializer.errors, status=400)
class OrderWithShipmentAPIView(APIView):
    def get(self, request):
        orders = Order.objects.filter(
            shipments__isnull=False
        ).prefetch_related("shipments").distinct()

        data = []
        for order in orders:
            shipments = order.shipments.all()  # ✅ optimize
            shipment_data = ShipmentSerializer(shipments, many=True).data

            data.append({
                "order_id": order.id,
                "customer_name": order.customer_name,
                "total_amount": order.total_amount,
                "shipments": shipment_data
            })

        return Response(data)
class OrderStatusListCreateView(APIView):
    permission_classes = []

    def get(self, request):
        order_id = request.query_params.get("order_id")
        if not order_id:
            return Response({"error": "order_id query param required"}, status=400)
        
        statuses = OrderStatus.objects.filter(order_id=order_id).order_by('-created_at')
        serializer = OrderStatusSerializer(statuses, many=True)
        return Response({"data": serializer.data, "count": statuses.count()})

    def post(self, request):
        serializer = OrderStatusSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Status created", "data": serializer.data}, status=201)
        return Response(serializer.errors, status=400)


class OrderStatusDetailView(APIView):
    permission_classes = []

    def get_object(self, pk):
        return OrderStatus.objects.filter(pk=pk).first()

    def get(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({"error": "Not found"}, status=404)
        serializer = OrderStatusSerializer(obj)
        return Response(serializer.data)

    def put(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({"error": "Not found"}, status=404)
        serializer = OrderStatusSerializer(obj, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Status updated", "data": serializer.data})
        return Response(serializer.errors, status=400)

    def patch(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({"error": "Not found"}, status=404)
        serializer = OrderStatusSerializer(obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Status updated", "data": serializer.data})
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({"error": "Not found"}, status=404)
        obj.delete()
        return Response({"message": "Status deleted"}, status=200)
# -------- Product Variants ----------------------------------------

class ProductVariantListCreateView(APIView):
    permission_classes = []

    def get(self, request, product_id):
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            return Response({"error": "Product not found"}, status=404)
        
        variants = ProductVariant.objects.none()
        
        serializer = ProductVariantSerializer(
            variants, many=True, context={'request': request}
        )
        return Response(serializer.data)

    def post(self, request, product_id):
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            return Response({"error": "Product not found"}, status=404)
        
        serializer = ProductVariantSerializer(
            data=request.data, context={'request': request}
        )
        if serializer.is_valid():
            variant = serializer.save()
            return Response(
                ProductVariantSerializer(variant, context={'request': request}).data,
                status=201
            )
        return Response(serializer.errors, status=400)


class ProductVariantDetailView(APIView):
    permission_classes = []

    def get_object(self, pk):
        return ProductVariant.objects.filter(pk=pk).prefetch_related("images").first()

    def get(self, request, pk):
        variant = self.get_object(pk)
        if not variant:
            return Response({"error": "Variant not found"}, status=404)
        return Response(
            ProductVariantSerializer(variant, context={'request': request}).data
        )

    def patch(self, request, pk):
        variant = self.get_object(pk)
        if not variant:
            return Response({"error": "Variant not found"}, status=404)
        
        serializer = ProductVariantSerializer(
            variant, data=request.data, partial=True, context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        variant = self.get_object(pk)
        if not variant:
            return Response({"error": "Variant not found"}, status=404)
        variant.delete()
        return Response({"message": "Variant deleted"}, status=200)


# -------- Variant Images ----------------------------------------

class ProductVariantImageUploadView(APIView):
    permission_classes = []

    def get(self, request, variant_id):
        variant = ProductVariant.objects.filter(pk=variant_id).first()
        if not variant:
            return Response({"error": "Variant not found"}, status=404)
        
        images = ProductVariantImage.objects.filter(variant=variant)
        serializer = ProductVariantImageSerializer(
            images, many=True, context={'request': request}
        )
        return Response(serializer.data)

    def post(self, request, variant_id):
        variant = ProductVariant.objects.filter(pk=variant_id).first()
        if not variant:
            return Response({"error": "Variant not found"}, status=404)
        
        files = request.FILES.getlist('images')
        if not files:
            return Response({"error": "No images provided"}, status=400)
        
        created = []
        for idx, file in enumerate(files):
            img = ProductVariantImage.objects.create(
                variant=variant,
                image=file,
                is_primary=(idx == 0 and not variant.images.exists()),
                order=variant.images.count() + idx
            )
            created.append(
                ProductVariantImageSerializer(img, context={'request': request}).data
            )
        
        return Response({
            "message": "Images uploaded successfully",
            "images": created
        }, status=201)

    def delete(self, request, variant_id):
        image_id = request.data.get("image_id")
        if not image_id:
            return Response({"error": "image_id required"}, status=400)
        
        img = ProductVariantImage.objects.filter(
            pk=image_id, variant_id=variant_id
        ).first()
        if not img:
            return Response({"error": "Image not found"}, status=404)
        
        img.delete()
        return Response({"message": "Image deleted"}, status=200)
    








class OrderListAPIView(APIView):
    permission_classes = []

    def get(self, request):
        status_filter = request.query_params.get("status")
        search = request.query_params.get("search", "").strip()

        orders = (
            Order.objects.filter(is_deleted=False)
            .select_related("channel")
            .prefetch_related("items__product", "remarks_list", "shipments")
            .order_by("-id")
        )

        STATUS_QUERY_MAP = {
            "IN_PROCESS": 1,
            "PACKED": 2,
            "IN_TRANSIT": 3,
            "DELIVERED": 4,
            "CANCELLED": 5,
            "COURIER_RETURN": 6,
            "CUSTOMER_RETURN": 7,
            "RETURNED": 8,
        }

        if search:
            search_filter = Q(customer_name__icontains=search)
            if search.isdigit():
                search_filter |= Q(id=int(search))
            orders = orders.filter(search_filter)

        orders = list(orders.distinct())
        order_ids = [order.id for order in orders]
        statuses = (
            OrderStatus.objects
            .filter(order_id__in=order_ids)
            .order_by("order_id", "-created_at")
        )
        latest_status_map = {}
        for status_obj in statuses:
            if status_obj.order_id not in latest_status_map:
                latest_status_map[status_obj.order_id] = status_obj

        for order in orders:
            latest_status = latest_status_map.get(order.id)
            order._prefetched_statuses = [latest_status] if latest_status else []

        if status_filter and status_filter.upper() != "ALL":
            status_code = STATUS_QUERY_MAP.get(status_filter.upper())
            if status_code:
                orders = [
                    order for order in orders
                    if (
                        latest_status_map[order.id].status
                        if order.id in latest_status_map
                        else order.order_status
                    ) == status_code
                ]

        serializer = OrderListSerializer(orders, many=True)

        return Response({
            "data": serializer.data,
            "count": len(orders)
        })

class OrderDetailAPIView(APIView):
    permission_classes = []

    def get(self, request, order_id):
        order = get_object_or_404(
            Order.objects.prefetch_related(
                "items__product",
                "shipments",
            ),
            id=order_id,
            is_deleted=False,
        )

        serializer = OrderDetailSerializer(order)
        data = serializer.data
        status_history = normalized_order_status_history(
            OrderStatus.objects.filter(order_id=order.id)
        )
        latest_status = status_history[-1] if status_history else None
        status_code = latest_status.status if latest_status else order.order_status
        data["order_status"] = status_code
        data["latest_status"] = {
            "status": status_code,
            "label": ORDER_STATUS_MAP.get(status_code, "Active"),
            "created_at": latest_status.created_at.isoformat() if latest_status and latest_status.created_at else "",
        }
        data["status"] = "Cancelled" if order.status == "CANCELLED" else ORDER_STATUS_MAP.get(status_code, "Active")
        data["status_date"] = latest_status.created_at.strftime("%d/%m/%Y - %H:%M") if latest_status and latest_status.created_at else ""
        data["status_timestamp"] = latest_status.created_at.isoformat() if latest_status and latest_status.created_at else ""

        qrcodes_dir = os.path.join(settings.MEDIA_ROOT, "qrcodes")
        os.makedirs(qrcodes_dir, exist_ok=True)
        for item in data.get("items", []):
            serials = []
            units = ProductUnit.objects.filter(
                order=order,
                product_id=item.get("product_id"),
                status="sold",
            ).order_by("serial_number")
            for unit in units:
                file_name = f"{unit.serial_number}.png"
                file_path = os.path.join(qrcodes_dir, file_name)
                if not os.path.exists(file_path):
                    qrcode.make(unit.serial_number).save(file_path)
                image_url = request.build_absolute_uri(
                    f"{settings.MEDIA_URL}qrcodes/{file_name}"
                )
                serials.append({
                    "serial_number": unit.serial_number,
                    "qr_image": image_url,
                    "barcode_image": image_url,
                })
            item["serials"] = serials
            if serials:
                item["serial"] = serials[0]["serial_number"]

        return Response(data)


class OrderSoftDeleteView(APIView):
    permission_classes = []

    def delete(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)

        if order.is_deleted:
            return Response({"message": "Order already deleted"}, status=400)

        order.is_deleted = True
        order.save(update_fields=["is_deleted"])

        return Response({
            "message": f"Order {order.id} soft deleted successfully"
        })


class CancelOrderView(APIView):
    permission_classes = []

    def post(self, request, order_id):
        order = get_object_or_404(
            Order.objects.prefetch_related("items__product"),
            id=order_id,
            is_deleted=False,
        )

        if order.status == "CANCELLED":
            return Response({"message": "Order already cancelled"}, status=400)

        has_returns = (
            order.customer_returns.exists()
            or order.courierreturn_set.exists()
        )

        if has_returns:
            return Response(
                {"message": "Cannot cancel order. Returns already processed."},
                status=400,
            )

        with transaction.atomic():
            for item in order.items.select_related("product"):
                product = item.product
                qty = item.quantity

                units = list(
                    ProductUnit.objects.select_for_update().filter(
                        product=product,
                        order=order,
                        status="sold",
                    )[:qty]
                )

                ProductUnit.objects.filter(
                    id__in=[unit.id for unit in units]
                ).update(
                    status="in_stock",
                    order=None,
                )

                inv, _ = Inventory.objects.select_for_update().get_or_create(
                    product=product
                )
                inv.quantity += qty
                inv.save(update_fields=["quantity"])

                StockMovement.objects.create(
                    product=product,
                    delta=qty,
                    reason="RETURN",
                    condition="OK",
                    note=f"Order cancelled #{order.id}",
                )

            order.status = "CANCELLED"
            order.order_status = 5
            order.save(update_fields=["status", "order_status"])
            OrderStatus.objects.create(
                order_id=order.id,
                status=5,
                json={"message": "Order cancelled"},
            )

        return Response({
            "message": f"Order {order.id} cancelled successfully"
        })


class PackOrderAPIView(APIView):
    permission_classes = []
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, order_id):
        order = get_object_or_404(
            Order.objects.prefetch_related("items__product"),
            id=order_id,
            is_deleted=False,
        )
        current_status = effective_order_status(order)
        if order.status == "CANCELLED" or current_status != 1:
            if order.order_status != current_status:
                order.order_status = current_status
                order.save(update_fields=["order_status"])
            return Response(
                {"message": "Only an in-process order can be packed."},
                status=400,
            )

        item = order.items.select_related("product").first()
        if not item or not item.product:
            return Response({"message": "Order has no product to pack."}, status=400)

        required = ("height", "width", "length", "dead_weight", "vol_weight")
        missing = [field for field in required if not request.data.get(field)]
        if missing:
            return Response(
                {"message": "Package dimensions and weight are required.", "missing_fields": missing},
                status=400,
            )

        product = item.product
        product.height = request.data["height"]
        product.width = request.data["width"]
        product.length = request.data["length"]
        product.weight_before = request.data["dead_weight"]
        product.weight_after = request.data.get("billed_weight") or request.data["vol_weight"]
        product_image = request.data.get("product_image")
        update_fields = ["height", "width", "length", "weight_before", "weight_after"]
        if product_image:
            product.product_image = str(product_image).replace(settings.MEDIA_URL, "", 1).lstrip("/")
            update_fields.append("product_image")

        with transaction.atomic():
            product.save(update_fields=update_fields)
            order.order_status = 2
            order.save(update_fields=["order_status"])
            OrderStatus.objects.create(
                order_id=order.id,
                status=2,
                json={
                    "message": "Package saved",
                    "package": {
                        "height": request.data["height"],
                        "width": request.data["width"],
                        "length": request.data["length"],
                        "dead_weight": request.data["dead_weight"],
                        "vol_weight": request.data["vol_weight"],
                        "billed_weight": request.data.get("billed_weight") or request.data["vol_weight"],
                    },
                },
            )

        return Response({
            "message": "Order packed successfully",
            "data": OrderDetailSerializer(order).data,
        })


class CourierPartnerCreateAPIView(APIView):
    permission_classes = []

    def post(self, request):
        serializer = CourierPartnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {
                "message": "Courier Partner Created Successfully",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


class CourierPartnerListAPIView(APIView):
    permission_classes = []

    def get(self, request):
        return Response({
            "data": courier_partner_payloads()
        })


class CreateShipmentFromOrderAPIView(APIView):
    permission_classes = []

    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id, is_deleted=False)
        current_status = effective_order_status(order)
        if current_status != 2:
            if order.order_status != current_status:
                order.order_status = current_status
                order.save(update_fields=["order_status"])
            return Response(
                {"message": "Shipment can only be created for a packed order."},
                status=400,
            )
        data = request.data.copy()
        data["order"] = order.id

        shipment = order.shipments.first()
        serializer = ShipmentSerializer(shipment, data=data, partial=bool(shipment))
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            serializer.save(order=order)
            order.order_status = 3
            order.save(update_fields=["order_status"])
            OrderStatus.objects.create(
                order_id=order.id,
                status=3,
                json={"message": "Shipment created"},
            )

        return Response(
            {
                "message": "Shipment saved for order",
                "data": serializer.data,
            },
            status=201,
        )


class OrderWithShipmentAPIView(APIView):
    permission_classes = []

    def get(self, request):
        orders = (
            Order.objects.filter(is_deleted=False, shipments__isnull=False)
            .prefetch_related("shipments")
            .distinct()
            .order_by("-id")
        )

        data = []

        for order in orders:
            data.append({
                "order_id": order.id,
                "customer_name": order.customer_name,
                "total_amount": order.total_amount,
                "shipments": ShipmentSerializer(
                    order.shipments.all(),
                    many=True
                ).data,
            })

        return Response({
            "data": data,
            "count": len(data)
        })


class OrderStatusListCreateView(APIView):
    permission_classes = []

    def get(self, request):
        order_id = request.query_params.get("order_id")

        if not order_id:
            return Response(
                {"error": "order_id query param required"},
                status=400,
            )

        statuses = normalized_order_status_history(
            OrderStatus.objects.filter(order_id=order_id)
        )

        serializer = OrderStatusSerializer(statuses, many=True)

        return Response({
            "data": serializer.data,
            "count": len(statuses)
        })

    def post(self, request):
        serializer = OrderStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        status_entry = serializer.save()

        Order.objects.filter(
            id=status_entry.order_id,
            is_deleted=False,
        ).update(order_status=status_entry.status)

        return Response(
            {
                "message": "Status created",
                "data": serializer.data,
            },
            status=201,
        )


class OrderStatusDetailView(APIView):
    permission_classes = []

    def get_object(self, pk):
        return OrderStatus.objects.filter(pk=pk).first()

    def get(self, request, pk):
        obj = self.get_object(pk)

        if not obj:
            return Response({"error": "Not found"}, status=404)

        serializer = OrderStatusSerializer(obj)
        return Response(serializer.data)

    def put(self, request, pk):
        obj = self.get_object(pk)

        if not obj:
            return Response({"error": "Not found"}, status=404)

        serializer = OrderStatusSerializer(obj, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            "message": "Status updated",
            "data": serializer.data,
        })

    def patch(self, request, pk):
        obj = self.get_object(pk)

        if not obj:
            return Response({"error": "Not found"}, status=404)

        serializer = OrderStatusSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            "message": "Status updated",
            "data": serializer.data,
        })

    def delete(self, request, pk):
        obj = self.get_object(pk)

        if not obj:
            return Response({"error": "Not found"}, status=404)

        obj.delete()

        return Response({
            "message": "Status deleted"
        }, status=200)


class MarkOrderDeliveredAPIView(APIView):
    permission_classes = []

    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id, is_deleted=False)
        latest_status = effective_order_status(order)

        if latest_status == 4:
            if order.order_status != 4:
                order.order_status = 4
                order.save(update_fields=["order_status"])
            return Response({"message": "Order already delivered."})
        if latest_status != 3:
            return Response(
                {"message": "Only an in-transit order can be delivered."},
                status=400,
            )

        order.order_status = 4
        order.save(update_fields=["order_status"])

        OrderStatus.objects.create(
            order_id=order.id,
            status=4,
            json={"message": "Order marked as delivered"}
        )

        return Response({
            "message": "Order marked as delivered"
        })

class SerialBarcodePDFAPIView(APIView):
    permission_classes = []

    def get(self, request, order_id):
        order = get_object_or_404(Order, id=order_id, is_deleted=False)
        serials = list(
            ProductUnit.objects
            .filter(order=order, status="sold")
            .order_by("serial_number")
            .values_list("serial_number", flat=True)
        )

        if not serials:
            return Response({"detail": "No serial QR codes found for this order."}, status=404)

        pages = []
        for serial in serials:
            qr_image = qrcode.make(serial).convert("RGB").resize((720, 720))
            page = qr_image.resize((720, 720))
            pages.append(page)

        pdf_buffer = BytesIO()
        pages[0].save(
            pdf_buffer,
            format="PDF",
            save_all=True,
            append_images=pages[1:],
            resolution=150,
        )

        response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="order-{order.id}-serial-qr-codes.pdf"'
        )

        return response
    
