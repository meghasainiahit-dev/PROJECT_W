from decimal import Decimal

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Sum, F, OuterRef, Subquery, IntegerField
from ..models import *
from ..serializers import *
from ..permissions import IsAuthenticatedDelete
from django.db.models import Q
from datetime import datetime, timedelta
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import AccessToken
import jwt
import uuid
from rest_framework.pagination import PageNumberPagination
from ..inventory_utils import add_inventory_with_serials
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from django.db import transaction
from rest_framework import status as http_status
from django.db import transaction
from ..models import PurchaseBill, PurchaseBillItem
class BillingPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200



# api use 
# Search customer/mobile/order-id	/api/all-bills?search=rahul
# Date Range	/api/all-bills?start_date=2025-01-01&end_date=2025-01-31
# Single Date	/api/all-bills?date=2025-02-12
# Channel Filter	/api/all-bills?channel_id=3
# Specific Order ID	/api/all-bills?order_id=22
# Pagination	/api/all-bills?page=2&page_size=50
#paid_status=PAID


class BillingView(APIView):
    permission_classes = []
    pagination_class = BillingPagination

    def get(self, request):

        queryset = Order.objects.all().order_by("-created_at")

        # ---------- FILTERS ----------

        search = request.GET.get("search")
        if search:
            queryset = queryset.filter(
                Q(id__icontains=search) |
                Q(mobile__icontains=search) |
                Q(customer_name__icontains=search) |
                Q(channel_order_id__icontains=search)
            )

        order_id = request.GET.get("order_id")
        if order_id:
            queryset = queryset.filter(id=order_id)

        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")
        if start_date and end_date:
            queryset = queryset.filter(created_at__date__range=[start_date, end_date])

        date = request.GET.get("date")
        if date:
            queryset = queryset.filter(created_at__date=date)

        channel_id = request.GET.get("channel_id")
        if channel_id:
            queryset = queryset.filter(channel_id=channel_id)

        paid_status = request.GET.get("paid_status")
        if paid_status is not None:
            queryset = queryset.filter(paid_status=paid_status)

        # ---------- PAGINATION ----------
        paginator = self.pagination_class()
        paginated_qs = paginator.paginate_queryset(queryset, request)

        # ---------- DEFAULT GST ----------
        default_gst_obj = HsnTable.objects.first()
        default_gst = (
            Decimal(default_gst_obj.gst_percentage)
            if default_gst_obj
            else Decimal("0.00")
        )

        response_data = []

        # ---------- GST CALCULATION ----------
        for order in paginated_qs:

            items = order.items.select_related("product__hsn").all()

            subtotal = Decimal("0.00")
            gst_amount = Decimal("0.00")

            for item in items:
                item_total = item.unit_price * item.quantity
                subtotal += item_total

                if item.product and item.product.hsn:
                    gst_percentage = item.product.hsn.gst_percentage
                else:
                    gst_percentage = default_gst

                gst_amount += (item_total * gst_percentage) / 100

            grand_total = subtotal + gst_amount

            order_data = OrderSerializer(order).data
            order_data["subtotal"] = round(subtotal, 2)
            order_data["gst_amount"] = round(gst_amount, 2)
            order_data["grand_total"] = round(grand_total, 2)
            order_data["paid_status"] = order.paid_status

            response_data.append(order_data)

        return paginator.get_paginated_response(response_data)



class BillingPertculerView(APIView):
    permission_classes = []

    def get(self, request, id):
        order = Order.objects.filter(id=id).first()
        if not order:
            return Response({"error": "Order not found"}, status=404)

        serializer = OrderSerializer(order)

        items = order.items.all()
        subtotal = Decimal("0.00")

        for item in items:
            subtotal += Decimal(item.unit_price) * Decimal(item.quantity)

        # ✅ FIXED: HsnTable used consistently
        gst_obj = HsnTable.objects.first()
        gst_percentage = Decimal(gst_obj.gst_percentage) if gst_obj else Decimal("0.00")

        gst_amount = (subtotal * gst_percentage) / 100
        grand_total = subtotal + gst_amount

        response = serializer.data
        response["subtotal"] = round(subtotal, 2)
        response["gst_percentage"] = gst_percentage
        response["gst_amount"] = round(gst_amount, 2)
        response["grand_total"] = round(grand_total, 2)
        

        return Response(response)

class _LegacyUpdatePaymentDetailsOrderView(APIView):
    permission_classes = []

    def post(self, request, order_id):
        try:
            order = Order.objects.filter(id=order_id).first()
            if not order:
                return Response({"error": "Order not found"}, status=404)

            amount = request.data.get("amount")
            payment_method = request.data.get("payment_method")
            transaction_id = request.data.get("transaction_id")
            payment_date = request.data.get("payment_date")

            # ✅ SAFE DECIMAL HANDLING
            if amount:
                try:
                    amount = Decimal(str(amount))
                except (InvalidOperation, ValueError):
                    return Response({"error": "Invalid amount"}, status=400)

                if amount > order.remaining_amount():
                    return Response({"error": "Amount exceeds remaining balance"}, status=400)

                order.paid_amount += amount

            if payment_method:
                order.payment_method = payment_method

            if transaction_id:
                order.transaction_id = transaction_id

            # ✅ DATE FIX
            if payment_date:
                try:
                    order.payment_date = datetime.strptime(payment_date, "%Y-%m-%d %H:%M")
                except:
                    try:
                        order.payment_date = datetime.strptime(payment_date, "%Y-%m-%d")
                    except:
                        return Response({"error": "Invalid date format"}, status=400)
            else:
                order.payment_date = timezone.now()

            order.update_payment_status()
            order.save()

            return Response({
                "message": "Payment updated successfully",
                "order_id": order.id,
                "paid_amount": str(order.paid_amount),
                "remaining_amount": str(order.remaining_amount()),
                "paid_status": order.paid_status,
            })

        except Exception as e:
            return Response({"error": str(e)}, status=500)
class UpdatePaymentDetailsOrderNewView(APIView):
    permission_classes = []

    def post(self, request, order_id):
        try:
            order = Order.objects.filter(id=order_id).first()
            if not order:
                return Response({"error": "Order not found"}, status=404)

            amount = request.data.get("amount")
            payment_method = request.data.get("payment_method")
            transaction_id = request.data.get("transaction_id")
            payment_date = request.data.get("payment_date")

            # ✅ SAFE DECIMAL HANDLING
            if amount:
                try:
                    amount = Decimal(str(amount))
                except (InvalidOperation, ValueError):
                    return Response({"error": "Invalid amount"}, status=400)

                if amount > order.remaining_amount():
                    return Response({"error": "Amount exceeds remaining balance"}, status=400)

                order.paid_amount += amount

            if payment_method:
                order.payment_method = payment_method

            if transaction_id:
                order.transaction_id = transaction_id

            # ✅ DATE FIX
            if payment_date:
                try:
                    order.payment_date = datetime.strptime(payment_date, "%Y-%m-%d %H:%M")
                except:
                    try:
                        order.payment_date = datetime.strptime(payment_date, "%Y-%m-%d")
                    except:
                        return Response({"error": "Invalid date format"}, status=400)
            else:
                order.payment_date = timezone.now()

            order.update_payment_status()
            order.save()

            return Response({
                "message": "Payment updated successfully",
                "order_id": order.id,
                "paid_amount": str(order.paid_amount),
                "remaining_amount": str(order.remaining_amount()),
                "paid_status": order.paid_status,
            })

        except Exception as e:
            return Response({"error": str(e)}, status=500)
        
        

# def generate_bill_number():
#     with transaction.atomic():
#         last_purchase = PurchaseBill.objects.select_for_update().order_by('-id').first()

#         if last_purchase and last_purchase.bill_number:
#             last_number = int(last_purchase.bill_number.split('-')[1])
#             new_number = last_number + 1
#         else:
#             new_number = 1

#         return f"PB-{str(new_number).zfill(4)}"
    
# class CreatePurchaseBillView(APIView):
#        permission_classes = []

#     def post(self, request):
#         data = request.data
#         items = data.get("items", [])

#         if not items:
#             return Response({"error": "Items are required"}, status=400)

#         vendor = Vendor.objects.filter(id=data.get("vendor")).first()
#         if not vendor:
#             return Response({"error": "Vendor not found"}, status=404)

#         bill_number = generate_bill_number()

#         with transaction.atomic():

#             bill = PurchaseBill.objects.create(
#                 vendor=vendor,
#                 bill_number=bill_number,
#                 bill_date=data.get("bill_date"),
#                 place_of_supply=data.get("place_of_supply"),
#                 gst_type=data.get("gst_type"),
#                 tax_type=data.get("tax_type"),
#                 sgst_percent=data.get("sgst_percent", 0),
#                 cgst_percent=data.get("cgst_percent", 0),
#                 igst_percent=data.get("igst_percent", 0),
#                 discount=data.get("discount", 0),
#                 shipping=data.get("shipping", 0),
#                 other_expense=data.get("other_expense", 0),
#                 round_off=data.get("round_off", 0),
#                 description=data.get("description"),
#                 paid_amount=data.get("paid_amount", 0),
#                 paid_date=data.get("paid_date"),
#                 status=data.get("status", "UNPAID"),
#             )

#             subtotal = Decimal("0.00")

#             for item in items:
#                 product = Product.objects.filter(id=item["product"]).first()
#                 if not product:
#                     return Response({"error": f"Product {item['product']} not found"}, status=404)

#                 quantity = Decimal(str(item["quantity"]))
#                 price = Decimal(str(item["unit_price"]))
#                 total = quantity * price

#                 PurchaseBillItem.objects.create(
#                     bill=bill,
#                     product=product,
#                     quantity=quantity,
#                     unit_price=price,
#                     total_price=total
#                 )

#                 subtotal += total

#             # ✅ SAVE TOTALS (IMPORTANT FIX)
#             bill.subtotal = subtotal
#             bill.save()

#         return Response({
#             "message": "Purchase bill created successfully",
#             "bill_id": bill.id,
#             "bill_number": bill.bill_number,
#             "subtotal": str(subtotal),
#         }, status=201)      
# class GetAllPurchase(APIView):
#        permission_classes = []

#     def get(self, request):

#         queryset = PurchaseBill.objects.all().order_by("-created_at")

#         # 🔍 FILTERS
#         vendor = request.GET.get("vendor")
#         if vendor:
#             queryset = queryset.filter(vendor_id=vendor)

#         status_filter = request.GET.get("status")
#         if status_filter:
#             queryset = queryset.filter(status=status_filter)

#         start_date = request.GET.get("start_date")
#         end_date = request.GET.get("end_date")
#         if start_date and end_date:
#             queryset = queryset.filter(bill_date__range=[start_date, end_date])

#         search = request.GET.get("search")
#         if search:
#             queryset = queryset.filter(
#                 Q(bill_number__icontains=search) |
#                 Q(vendor__name__icontains=search)
#             )

#         results = []

#         for bill in queryset:

#             items_qs = bill.items.select_related("product").all()

#             results.append({
#                 "id": bill.id,
#                 "bill_number": bill.bill_number,

#                 "vendor": {
#                     "id": bill.vendor.id,
#                     "name": bill.vendor.name,
#                 },

#                 "subtotal": float(bill.subtotal),
#                 "total_amount": float(bill.total_amount),
#                 "paid_amount": float(bill.paid_amount),
#                 "remaining_amount": float(bill.remaining_amount()),

#                 "status": bill.status,

#                 "items": PurchaseBillSerializer(items_qs, many=True).data
#             })

#         return Response({
#             "count": queryset.count(),
#             "results": results
#         }, status=status.HTTP_200_OK)
# class UpdatePurchaseBillView(APIView):
#        permission_classes = []

#     def put(self, request, id):

#         bill = PurchaseBill.objects.filter(id=id, is_deleted=False).first()
#         if not bill:
#             return Response({"error": "Bill not found"}, status=404)

#         data = request.data

#         # =========================
#         # 1. BILL BASIC FIELDS
#         # =========================
#         bill.bill_date = data.get("bill_date", bill.bill_date)
#         bill.discount = Decimal(str(data.get("discount", bill.discount)))
#         bill.shipping = Decimal(str(data.get("shipping", bill.shipping)))
#         bill.other_expense = Decimal(str(data.get("other_expense", bill.other_expense)))
#         bill.paid_amount = Decimal(str(data.get("paid_amount", bill.paid_amount)))

#         # =========================
#         # 2. ITEMS UPDATE (FULL RESET APPROACH)
#         # =========================
#         items = data.get("items", None)

#         if items is not None:

#             # ❌ delete old items
#             bill.items.all().delete()

#             subtotal = Decimal("0")

#             # ✔ create new items
#             for i in items:
#                 product = Product.objects.filter(id=i["product"]).first()
#                 if not product:
#                     return Response({"error": "Product not found"}, status=404)

#                 qty = Decimal(str(i["quantity"]))
#                 price = Decimal(str(i["unit_price"]))
#                 total = qty * price

#                 PurchaseBillItem.objects.create(
#                     bill=bill,
#                     product=product,
#                     quantity=qty,
#                     unit_price=price,
#                     total_price=total
#                 )

#                 subtotal += total

#             bill.subtotal = subtotal

#         # =========================
#         # 3. TOTAL CALCULATION
#         # =========================
#         bill.total_amount = (
#             bill.subtotal
#             - bill.discount
#             + bill.shipping
#             + bill.other_expense
#         )

#         # =========================
#         # 4. STATUS UPDATE
#         # =========================
#         bill.update_payment_status()

#         bill.save()

#         return Response({
#             "message": "Purchase bill fully updated",
#             "bill_id": bill.id,
#             "subtotal": float(bill.subtotal),
#             "total_amount": float(bill.total_amount),
#             "paid_amount": float(bill.paid_amount),
#             "remaining_amount": float(bill.remaining_amount()),
#             "status": bill.status
#         })

# class DeletePurchaseBillView(APIView):
#     #    permission_classes = []

#     # def delete(self, request, id):

#     #     bill = PurchaseBill.objects.filter(id=id, is_deleted=False).first()
#     #     if not bill:
#     #         return Response({"error": "Bill not found"}, status=404)

#     #     # 🔥 soft delete
#     #     bill.is_deleted = True
#     #     bill.save()

#     #     return Response({
#     #         "message": "Purchase bill deleted (soft delete)"
#     #     })


# # apne actual imports ke hisaab se names adjust kar lena
# # from .models import Vendor, Product, PurchaseBill, PurchaseBillItem, Inventory
# # from .serializers import PurchaseBillItemSerializer


# def calculate_purchase_totals(bill):
#     tax_percent = (
#         Decimal(str(bill.sgst_percent or 0)) +
#         Decimal(str(bill.cgst_percent or 0)) +
#         Decimal(str(bill.igst_percent or 0))
#     )

#     bill.tax_amount = (bill.subtotal * tax_percent) / Decimal("100")

#     bill.total_amount = (
#         bill.subtotal
#         + bill.tax_amount
#         - Decimal(str(bill.discount or 0))
#         + Decimal(str(bill.shipping or 0))
#         + Decimal(str(bill.other_expense or 0))
#         + Decimal(str(bill.round_off or 0))
#     )

#     bill.update_payment_status()
#     return bill


# def reverse_purchase_stock(bill):
#     for item in bill.items.all():
#         inventory = Inventory.objects.filter(product=item.product).first()
#         if inventory:
#             inventory.quantity = max(0, inventory.quantity - item.quantity)
#             inventory.save()


# class CreatePurchaseBillView(APIView):
#        permission_classes = []

#     def post(self, request):
#         data = request.data
#         items = data.get("items", [])

#         if not items:
#             return Response({"error": "Items are required"}, status=400)

#         vendor = Vendor.objects.filter(id=data.get("vendor")).first()
#         if not vendor:
#             return Response({"error": "Vendor not found"}, status=404)

#         # Pehle items validate karo, bill baad me create karo
#         validated_items = []
#         for item in items:
#             product_id = item.get("product")
#             quantity = item.get("quantity")
#             unit_price = item.get("unit_price")

#             if not product_id or quantity is None or unit_price is None:
#                 return Response(
#                     {"error": "Each item must have product, quantity and unit_price"},
#                     status=400
#                 )

#             product = Product.objects.filter(id=product_id).first()
#             if not product:
#                 return Response({"error": f"Product {product_id} not found"}, status=404)

#             validated_items.append({
#                 "product": product,
#                 "quantity": int(quantity),
#                 "unit_price": Decimal(str(unit_price)),
#             })

#         bill_number = generate_bill_number()

#         with transaction.atomic():
#             bill = PurchaseBill.objects.create(
#                 vendor=vendor,
#                 bill_number=bill_number,
#                 bill_date=data.get("bill_date"),
#                 place_of_supply=data.get("place_of_supply"),
#                 gst_type=data.get("gst_type"),
#                 tax_type=data.get("tax_type"),
#                 sgst_percent=Decimal(str(data.get("sgst_percent", 0))),
#                 cgst_percent=Decimal(str(data.get("cgst_percent", 0))),
#                 igst_percent=Decimal(str(data.get("igst_percent", 0))),
#                 discount=Decimal(str(data.get("discount", 0))),
#                 shipping=Decimal(str(data.get("shipping", 0))),
#                 other_expense=Decimal(str(data.get("other_expense", 0))),
#                 round_off=Decimal(str(data.get("round_off", 0))),
#                 description=data.get("description"),
#                 paid_amount=Decimal(str(data.get("paid_amount", 0))),
#                 paid_date=data.get("paid_date"),
#             )

#             subtotal = Decimal("0.00")

#             for item in validated_items:
#                 total = item["quantity"] * item["unit_price"]

#                 PurchaseBillItem.objects.create(
#                     bill=bill,
#                     product=item["product"],
#                     quantity=item["quantity"],
#                     unit_price=item["unit_price"],
#                     total_price=total
#                 )

#                 subtotal += total

#             bill.subtotal = subtotal
#             calculate_purchase_totals(bill)
#             bill.save()

#         return Response({
#             "message": "Purchase bill created successfully",
#             "bill_id": bill.id,
#             "bill_number": bill.bill_number,
#             "subtotal": str(bill.subtotal),
#             "tax_amount": str(bill.tax_amount),
#             "total_amount": str(bill.total_amount),
#             "status": bill.status,
#         }, status=201)

# class GetAllPurchase(APIView):
#        permission_classes = []

#     def get(self, request):
#         queryset = PurchaseBill.objects.filter(is_deleted=False).order_by("-created_at")

#         vendor = request.GET.get("vendor")
#         if vendor:
#             queryset = queryset.filter(vendor_id=vendor)

#         status_filter = request.GET.get("status")
#         if status_filter:
#             queryset = queryset.filter(status=status_filter)

#         start_date = request.GET.get("start_date")
#         end_date = request.GET.get("end_date")
#         if start_date and end_date:
#             queryset = queryset.filter(bill_date__range=[start_date, end_date])

#         search = request.GET.get("search")
#         if search:
#             queryset = queryset.filter(
#                 Q(bill_number__icontains=search) |
#                 Q(vendor__name__icontains=search)
#             )

#         serializer = PurchaseBillSerializer(queryset, many=True)

#         return Response({
#             "count": queryset.count(),
#             "results": serializer.data
#         }, status=status.HTTP_200_OK)


# class UpdatePurchaseBillView(APIView):
#        permission_classes = []

#     def put(self, request, id):
#         bill = PurchaseBill.objects.filter(id=id, is_deleted=False).first()
#         if not bill:
#             return Response({"error": "Bill not found"}, status=404)

#         data = request.data
#         items = data.get("items", None)

#         validated_items = []
#         if items is not None:
#             if not items:
#                 return Response({"error": "Items are required"}, status=400)

#             for item in items:
#                 product_id = item.get("product")
#                 quantity = item.get("quantity")
#                 unit_price = item.get("unit_price")

#                 if not product_id or quantity is None or unit_price is None:
#                     return Response(
#                         {"error": "Each item must have product, quantity and unit_price"},
#                         status=400
#                     )

#                 product = Product.objects.filter(id=product_id).first()
#                 if not product:
#                     return Response({"error": f"Product {product_id} not found"}, status=404)

#                 validated_items.append({
#                     "product": product,
#                     "quantity": int(quantity),
#                     "unit_price": Decimal(str(unit_price)),
#                 })

#         with transaction.atomic():
#             bill.bill_date = data.get("bill_date", bill.bill_date)
#             bill.place_of_supply = data.get("place_of_supply", bill.place_of_supply)
#             bill.gst_type = data.get("gst_type", bill.gst_type)
#             bill.tax_type = data.get("tax_type", bill.tax_type)
#             bill.sgst_percent = Decimal(str(data.get("sgst_percent", bill.sgst_percent)))
#             bill.cgst_percent = Decimal(str(data.get("cgst_percent", bill.cgst_percent)))
#             bill.igst_percent = Decimal(str(data.get("igst_percent", bill.igst_percent)))
#             bill.discount = Decimal(str(data.get("discount", bill.discount)))
#             bill.shipping = Decimal(str(data.get("shipping", bill.shipping)))
#             bill.other_expense = Decimal(str(data.get("other_expense", bill.other_expense)))
#             bill.round_off = Decimal(str(data.get("round_off", bill.round_off)))
#             bill.paid_amount = Decimal(str(data.get("paid_amount", bill.paid_amount)))
#             bill.paid_date = data.get("paid_date", bill.paid_date)
#             bill.description = data.get("description", bill.description)

#             if items is not None:
#                 reverse_purchase_stock(bill)
#                 bill.items.all().delete()

#                 subtotal = Decimal("0.00")

#                 for item in validated_items:
#                     total = item["quantity"] * item["unit_price"]

#                     PurchaseBillItem.objects.create(
#                         bill=bill,
#                         product=item["product"],
#                         quantity=item["quantity"],
#                         unit_price=item["unit_price"],
#                         total_price=total
#                     )

#                     subtotal += total

#                 bill.subtotal = subtotal

#             calculate_purchase_totals(bill)
#             bill.save()

#         return Response({
#             "message": "Purchase bill updated successfully",
#             "bill_id": bill.id,
#             "subtotal": float(bill.subtotal),
#             "tax_amount": float(bill.tax_amount),
#             "total_amount": float(bill.total_amount),
#             "paid_amount": float(bill.paid_amount),
#             "remaining_amount": float(bill.remaining_amount()),
#             "status": bill.status
#         })

# 
# class DeletePurchaseBillView(APIView):
#        permission_classes = []

#     def delete(self, request, id):
#         bill = PurchaseBill.objects.filter(id=id, is_deleted=False).first()
#         if not bill:
#             return Response({"error": "Bill not found"}, status=404)

#         with transaction.atomic():
#             reverse_purchase_stock(bill)
#             bill.is_deleted = True
#             bill.save()

#         return Response({
#             "message": "Purchase bill deleted successfully"
#         })


def to_decimal(value, default="0"):
    try:
        return Decimal(str(value if value is not None else default))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def generate_bill_number():
    with transaction.atomic():
        last_purchase = (
            PurchaseBill.objects
            .select_for_update()
            .order_by("-id")
            .first()
        )

        if last_purchase and last_purchase.bill_number:
            try:
                last_number = int(last_purchase.bill_number.split("-")[1])
                new_number = last_number + 1
            except (IndexError, ValueError):
                new_number = last_purchase.id + 1
        else:
            new_number = 1

        return f"PB-{str(new_number).zfill(4)}"


def calculate_purchase_totals(bill):
    subtotal = to_decimal(bill.subtotal)
    sgst = to_decimal(bill.sgst_percent)
    cgst = to_decimal(bill.cgst_percent)
    igst = to_decimal(bill.igst_percent)

    discount = to_decimal(bill.discount)
    shipping = to_decimal(bill.shipping)
    other_expense = to_decimal(bill.other_expense)
    round_off = to_decimal(bill.round_off)

    tax_percent = sgst + cgst + igst
    bill.tax_amount = (subtotal * tax_percent) / Decimal("100")

    bill.total_amount = (
        subtotal
        + bill.tax_amount
        - discount
        + shipping
        + other_expense
        + round_off
    )

    bill.update_payment_status()
    return bill


def reverse_purchase_stock(bill):
    for item in bill.items.select_related("product").all():
        inventory = Inventory.objects.filter(product=item.product).first()
        if inventory:
            inventory.quantity = max(0, inventory.quantity - item.quantity)
            inventory.save()


def validate_purchase_items(items):
    if not items:
        return None, Response({"error": "Items are required"}, status=400)

    validated_items = []

    for item in items:
        product_id = item.get("product")
        quantity = item.get("quantity")
        unit_price = item.get("unit_price")

        if not product_id or quantity is None or unit_price is None:
            return None, Response(
                {"error": "Each item must have product, quantity and unit_price"},
                status=400
            )

        product = Product.objects.filter(id=product_id).first()
        if not product:
            return None, Response(
                {"error": f"Product {product_id} not found"},
                status=404
            )

        try:
            quantity = int(quantity)
        except (ValueError, TypeError):
            return None, Response({"error": "Quantity must be a number"}, status=400)

        if quantity <= 0:
            return None, Response({"error": "Quantity must be greater than 0"}, status=400)

        price = to_decimal(unit_price)
        if price < 0:
            return None, Response({"error": "Unit price cannot be negative"}, status=400)

        validated_items.append({
            "product": product,
            "quantity": quantity,
            "unit_price": price,
        })

    return validated_items, None


VALID_GST_TYPES     = ["with_gst", "no_gst"]
VALID_PAYMENT_MODES = ["cash", "bank_transfer", "upi", None]
 
 
# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def to_decimal(value, default="0"):
    """Any value ko safely Decimal mein convert karo."""
    try:
        return Decimal(str(value if value is not None else default))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)
 
 
def generate_bill_number():
    """Sequential bill number: PB-0001, PB-0002 ..."""
    with transaction.atomic():
        last = (
            PurchaseBill.objects
            .select_for_update()
            .order_by("-id")
            .first()
        )
        if last and last.bill_number:
            try:
                last_num = int(last.bill_number.split("-")[1])
                new_num  = last_num + 1
            except (IndexError, ValueError):
                new_num = (last.id or 0) + 1
        else:
            new_num = 1
        return f"PB-{str(new_num).zfill(4)}"
 
 
def calculate_purchase_totals(bill):
    """
    gst_type = 'with_gst'  → GST calculate karo (sgst+cgst OR igst)
    gst_type = 'no_gst'    → tax = 0, sirf subtotal + extras
 
    Formula:
        taxable_base = subtotal - discount
        tax_amount   = taxable_base × (sgst+cgst+igst) / 100   [only with_gst]
        total_amount = taxable_base + tax_amount + shipping + other_expense + round_off
    """
    subtotal      = to_decimal(bill.subtotal)
    discount      = to_decimal(bill.discount)
    shipping      = to_decimal(bill.shipping)
    other_expense = to_decimal(bill.other_expense)
    round_off     = to_decimal(bill.round_off)
 
    taxable_base = subtotal - discount
    if taxable_base < Decimal("0.00"):
        taxable_base = Decimal("0.00")
 
    if bill.gst_type == "with_gst":
        tax_percent = (
            to_decimal(bill.sgst_percent) +
            to_decimal(bill.cgst_percent) +
            to_decimal(bill.igst_percent)
        )
        bill.tax_amount = (taxable_base * tax_percent / Decimal("100")).quantize(Decimal("0.01"))
    else:
        # no_gst → tax zero
        bill.tax_amount   = Decimal("0.00")
        bill.sgst_percent = Decimal("0.00")
        bill.cgst_percent = Decimal("0.00")
        bill.igst_percent = Decimal("0.00")
 
    bill.total_amount = (
        taxable_base + bill.tax_amount + shipping + other_expense + round_off
    ).quantize(Decimal("0.01"))
 
    # ── Auto payment status ───────────────────────────────────────────────────
    paid = to_decimal(bill.paid_amount)
    if paid <= Decimal("0.00"):
        bill.status = "UNPAID"
    elif paid >= bill.total_amount:
        bill.status = "PAID"
    else:
        bill.status = "PARTIAL"
 
 
def reverse_purchase_stock(bill):
    """Bill delete/update hone par stock wapas ghatao."""
    for item in bill.items.select_related("product").all():
        inventory = Inventory.objects.filter(product=item.product).first()
        if inventory:
            inventory.quantity = max(0, inventory.quantity - item.quantity)
            inventory.save()
 
 
def validate_purchase_items(items):
    """
    Items list validate karo.
    Returns: (validated_items, error_response)
    error_response is None if valid.
    """
    if not items:
        return None, Response({"error": "Items are required"}, status=400)
 
    validated = []
    for item in items:
        product_id = item.get("product")
        quantity   = item.get("quantity")
        unit_price = item.get("unit_price")
 
        if not product_id or quantity is None or unit_price is None:
            return None, Response(
                {"error": "Each item must have product, quantity and unit_price"},
                status=400
            )
 
        product = Product.objects.filter(id=product_id).first()
        if not product:
            return None, Response(
                {"error": f"Product {product_id} not found"},
                status=404
            )
 
        try:
            qty = int(quantity)
            if qty <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return None, Response(
                {"error": "Quantity must be a positive integer"},
                status=400
            )
 
        price = to_decimal(unit_price)
        if price < 0:
            return None, Response(
                {"error": "Unit price cannot be negative"},
                status=400
            )
 
        validated.append({
            "product":    product,
            "quantity":   qty,
            "unit_price": price,
        })
 
    return validated, None
 
 
def purchase_value(data, key, bill=None):
    if key in data:
        return data.get(key)
    if bill is not None:
        return getattr(bill, key)
    return None


def projected_purchase_total(data, validated_items, gst_type, bill=None):
    subtotal = sum(
        item["quantity"] * item["unit_price"]
        for item in validated_items
    )
    discount = to_decimal(purchase_value(data, "discount", bill))
    shipping = to_decimal(purchase_value(data, "shipping", bill))
    other_expense = to_decimal(purchase_value(data, "other_expense", bill))
    round_off = to_decimal(purchase_value(data, "round_off", bill))
    taxable_base = subtotal - discount
    if taxable_base < Decimal("0.00"):
        taxable_base = Decimal("0.00")
    tax_amount = Decimal("0.00")
    if gst_type == "with_gst":
        tax_percent = (
            to_decimal(purchase_value(data, "sgst_percent", bill))
            + to_decimal(purchase_value(data, "cgst_percent", bill))
            + to_decimal(purchase_value(data, "igst_percent", bill))
        )
        tax_amount = (taxable_base * tax_percent / Decimal("100")).quantize(Decimal("0.01"))
    return (taxable_base + tax_amount + shipping + other_expense + round_off).quantize(Decimal("0.01"))


def validate_purchase_amounts(data, subtotal, gst_type, bill=None):
    for key, label in [
        ("discount", "Discount"),
        ("shipping", "Shipping"),
        ("other_expense", "Other expense"),
    ]:
        if to_decimal(purchase_value(data, key, bill)) < Decimal("0.00"):
            return Response({"error": f"{label} cannot be negative"}, status=400)

    if to_decimal(purchase_value(data, "discount", bill)) > subtotal:
        return Response({"error": "Discount cannot be greater than subtotal"}, status=400)

    if gst_type == "with_gst":
        for key, label in [
            ("sgst_percent", "SGST"),
            ("cgst_percent", "CGST"),
            ("igst_percent", "IGST"),
        ]:
            if to_decimal(purchase_value(data, key, bill)) < Decimal("0.00"):
                return Response({"error": f"{label} percent cannot be negative"}, status=400)
    return None


def validate_purchase_payment(data, total_amount, bill=None):
    paid_amount = to_decimal(purchase_value(data, "paid_amount", bill))
    due_date = purchase_value(data, "payment_due_date", bill)
    if paid_amount < Decimal("0.00"):
        return Response({"error": "Paid amount cannot be negative"}, status=400)
    if paid_amount > total_amount:
        return Response({"error": "Paid amount cannot be greater than total amount"}, status=400)
    if Decimal("0.00") < paid_amount < total_amount and not due_date:
        return Response({"error": "Payment due date is required for partial payment"}, status=400)
    return None


def _bill_response(message, bill):
    """
    Consistent response dict — har jagah same structure.
    no_gst hone par tax fields False return honge.
    remaining_amount = total - paid (kabhi negative nahi).
    """
    with_gst = bill.gst_type == "with_gst"
    paid     = to_decimal(bill.paid_amount)
    total    = to_decimal(bill.total_amount)
    remaining = max(total - paid, Decimal("0.00"))
 
    return {
        "message":          message,
        "bill_id":          bill.id,
        "bill_number":      bill.bill_number,
        "gst_type":         bill.gst_type,
 
        # GST fields — False when no_gst
        "sgst_percent":     str(bill.sgst_percent) if with_gst else False,
        "cgst_percent":     str(bill.cgst_percent) if with_gst else False,
        "igst_percent":     str(bill.igst_percent) if with_gst else False,
        "tax_amount":       str(bill.tax_amount)   if with_gst else False,
 
        # Amount breakdown
        "subtotal":         str(bill.subtotal),
        "discount":         str(bill.discount),
        "shipping":         str(bill.shipping),
        "other_expense":    str(bill.other_expense),
        "round_off":        str(bill.round_off),
 
        # Final totals
        "total_amount":     str(bill.total_amount),
        "paid_amount":      str(bill.paid_amount),
        "remaining_amount": str(remaining),          # total - paid
 
        # Payment info
        "payment_status":   bill.status,             # PAID / UNPAID / PARTIAL
        "payment_mode":     bill.payment_mode,
        "transaction_id":   bill.transaction_id,
        "payment_due_date": bill.payment_due_date,
    }
 
 
# ─────────────────────────────────────────────────────────────────────────────
# CREATE
# ─────────────────────────────────────────────────────────────────────────────
class CreatePurchaseBillView(APIView):
    permission_classes = []
 
    def post(self, request):
        data  = request.data
        items = data.get("items", [])

        bill_number = str(data.get("bill_number") or "").strip()
        if not bill_number:
            return Response({"error": "Bill number is required"}, status=400)
        if PurchaseBill.objects.filter(bill_number=bill_number).exists():
            return Response({"error": "Bill number already exists"}, status=400)
 
        # ── Vendor ───────────────────────────────────────────────────────────
        vendor = Vendor.objects.filter(id=data.get("vendor")).first()
        if not vendor:
            return Response({"error": "Vendor not found"}, status=404)
 
        # ── Items ────────────────────────────────────────────────────────────
        validated_items, err = validate_purchase_items(items)
        if err:
            return err
 
        # ── GST type ─────────────────────────────────────────────────────────
        gst_type = data.get("gst_type", "with_gst")
        if gst_type not in VALID_GST_TYPES:
            return Response(
                {"error": "gst_type must be 'with_gst' or 'no_gst'"},
                status=400
            )
        subtotal_preview = sum(
            item["quantity"] * item["unit_price"]
            for item in validated_items
        )
        amount_error = validate_purchase_amounts(data, subtotal_preview, gst_type)
        if amount_error:
            return amount_error
        total_preview = projected_purchase_total(data, validated_items, gst_type)
        payment_error = validate_purchase_payment(data, total_preview)
        if payment_error:
            return payment_error
 
        # ── Payment mode ─────────────────────────────────────────────────────
        payment_mode = data.get("payment_mode") or None
        if payment_mode not in VALID_PAYMENT_MODES:
            return Response(
                {"error": "payment_mode must be 'cash', 'bank_transfer' or 'upi'"},
                status=400
            )
 
        # transaction_id required for upi / bank_transfer
        transaction_id = data.get("transaction_id") or None
        if payment_mode in ("upi", "bank_transfer") and not transaction_id:
            return Response(
                {"error": f"transaction_id is required for {payment_mode}"},
                status=400
            )
 
        with transaction.atomic():
            bill = PurchaseBill.objects.create(
                vendor          = vendor,
                bill_number     = bill_number,
                bill_date       = data.get("bill_date"),
                place_of_supply = data.get("place_of_supply"),
 
                gst_type        = gst_type,
                # no_gst hone par percent 0 save hoga
                sgst_percent    = to_decimal(data.get("sgst_percent")) if gst_type == "with_gst" else Decimal("0"),
                cgst_percent    = to_decimal(data.get("cgst_percent")) if gst_type == "with_gst" else Decimal("0"),
                igst_percent    = to_decimal(data.get("igst_percent")) if gst_type == "with_gst" else Decimal("0"),
 
                discount        = to_decimal(data.get("discount")),
                shipping        = to_decimal(data.get("shipping")),
                other_expense   = to_decimal(data.get("other_expense")),
                round_off       = to_decimal(data.get("round_off")),
                description     = data.get("description"),
 
                paid_amount     = to_decimal(data.get("paid_amount")),
                paid_date       = data.get("paid_date"),
                payment_due_date = data.get("payment_due_date") or None,
                payment_mode    = payment_mode,
                transaction_id  = transaction_id,
            )
 
            subtotal = Decimal("0.00")
            for item in validated_items:
                total = item["quantity"] * item["unit_price"]
                PurchaseBillItem.objects.create(
                    bill        = bill,
                    product     = item["product"],
                    quantity    = item["quantity"],
                    unit_price  = item["unit_price"],
                    total_price = total,
                )
                subtotal += total
 
            bill.subtotal = subtotal
            calculate_purchase_totals(bill)   # tax, total, status sab set hoga
            if bill.status != "PARTIAL":
                bill.payment_due_date = None
            bill.save()
 
        return Response(
            _bill_response("Purchase bill created successfully", bill),
            status=http_status.HTTP_201_CREATED,
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# LIST  (GET ALL)
# ─────────────────────────────────────────────────────────────────────────────
class GetAllPurchase(APIView):
    permission_classes = []
 
    def get(self, request):
        queryset = PurchaseBill.objects.filter(is_deleted=False).order_by("-created_at")
 
        # ?vendor=<id>
        vendor = request.GET.get("vendor")
        if vendor:
            queryset = queryset.filter(vendor_id=vendor)
 
        # ?status=PAID | UNPAID | PARTIAL
        status_filter = request.GET.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter.upper())
 
        # ?gst_type=with_gst | no_gst
        gst_type_filter = request.GET.get("gst_type")
        if gst_type_filter:
            queryset = queryset.filter(gst_type=gst_type_filter)
 
        # ?payment_mode=cash | upi | bank_transfer
        payment_mode_filter = request.GET.get("payment_mode")
        if payment_mode_filter:
            queryset = queryset.filter(payment_mode=payment_mode_filter)
 
        # ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
        start_date = request.GET.get("start_date")
        end_date   = request.GET.get("end_date")
        if start_date and end_date:
            queryset = queryset.filter(bill_date__range=[start_date, end_date])
 
        # ?search=<bill_number or vendor name>
        search = request.GET.get("search")
        if search:
            queryset = queryset.filter(
                Q(bill_number__icontains=search) |
                Q(vendor__name__icontains=search)
            )
 
        serializer = PurchaseBillSerializer(queryset, many=True)
        return Response(
            {"count": queryset.count(), "results": serializer.data},
        
            status=http_status.HTTP_200_OK,
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# UPDATE
# ─────────────────────────────────────────────────────────────────────────────
class UpdatePurchaseBillView(APIView):
    permission_classes = []
 
    def put(self, request, id):
        bill = PurchaseBill.objects.filter(id=id, is_deleted=False).first()
        if not bill:
            return Response({"error": "Bill not found"}, status=404)
 
        data  = request.data
        items = data.get("items", None)

        bill_number = str(data.get("bill_number", bill.bill_number) or "").strip()
        if not bill_number:
            return Response({"error": "Bill number is required"}, status=400)
        if PurchaseBill.objects.filter(bill_number=bill_number).exclude(id=bill.id).exists():
            return Response({"error": "Bill number already exists"}, status=400)
 
        # ── Items (optional) ─────────────────────────────────────────────────
        validated_items = None
        if items is not None:
            validated_items, err = validate_purchase_items(items)
            if err:
                return err
 
        # ── GST type ─────────────────────────────────────────────────────────
        gst_type = data.get("gst_type", bill.gst_type)
        if gst_type not in VALID_GST_TYPES:
            return Response(
                {"error": "gst_type must be 'with_gst' or 'no_gst'"},
                status=400
            )
        preview_items = validated_items
        if preview_items is None:
            preview_items = [
                {
                    "product": item.product,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                }
                for item in bill.items.select_related("product").all()
            ]
        subtotal_preview = sum(
            item["quantity"] * item["unit_price"]
            for item in preview_items
        )
        amount_error = validate_purchase_amounts(data, subtotal_preview, gst_type, bill)
        if amount_error:
            return amount_error
        total_preview = projected_purchase_total(data, preview_items, gst_type, bill)
        payment_error = validate_purchase_payment(data, total_preview, bill)
        if payment_error:
            return payment_error
 
        # ── Payment mode ─────────────────────────────────────────────────────
        payment_mode = data.get("payment_mode", bill.payment_mode) or None
        if payment_mode not in VALID_PAYMENT_MODES:
            return Response(
                {"error": "payment_mode must be 'cash', 'bank_transfer' or 'upi'"},
                status=400
            )
 
        transaction_id = data.get("transaction_id", bill.transaction_id) or None
        if payment_mode in ("upi", "bank_transfer") and not transaction_id:
            return Response(
                {"error": f"transaction_id is required for {payment_mode}"},
                status=400
            )
 
        with transaction.atomic():
            bill.bill_number     = bill_number
            bill.bill_date       = data.get("bill_date",       bill.bill_date)
            bill.place_of_supply = data.get("place_of_supply", bill.place_of_supply)
            bill.description     = data.get("description",     bill.description)
            bill.paid_date       = data.get("paid_date",       bill.paid_date)
            bill.payment_due_date = data.get("payment_due_date", bill.payment_due_date) or None
 
            bill.gst_type        = gst_type
            bill.discount        = to_decimal(data.get("discount",      bill.discount))
            bill.shipping        = to_decimal(data.get("shipping",      bill.shipping))
            bill.other_expense   = to_decimal(data.get("other_expense", bill.other_expense))
            bill.round_off       = to_decimal(data.get("round_off",     bill.round_off))
            bill.paid_amount     = to_decimal(data.get("paid_amount",   bill.paid_amount))
            bill.payment_mode    = payment_mode
            bill.transaction_id  = transaction_id
 
            # GST percents: with_gst → update, no_gst → zero
            if gst_type == "with_gst":
                bill.sgst_percent = to_decimal(data.get("sgst_percent", bill.sgst_percent))
                bill.cgst_percent = to_decimal(data.get("cgst_percent", bill.cgst_percent))
                bill.igst_percent = to_decimal(data.get("igst_percent", bill.igst_percent))
            else:
                bill.sgst_percent = Decimal("0.00")
                bill.cgst_percent = Decimal("0.00")
                bill.igst_percent = Decimal("0.00")
 
            # ── Items update ──────────────────────────────────────────────────
            if validated_items is not None:
                reverse_purchase_stock(bill)
                bill.items.all().delete()
 
                subtotal = Decimal("0.00")
                for item in validated_items:
                    total = item["quantity"] * item["unit_price"]
                    PurchaseBillItem.objects.create(
                        bill        = bill,
                        product     = item["product"],
                        quantity    = item["quantity"],
                        unit_price  = item["unit_price"],
                        total_price = total,
                    )
                    subtotal += total
                bill.subtotal = subtotal
 
            calculate_purchase_totals(bill)   # tax, total, status recalculate
            if bill.status != "PARTIAL":
                bill.payment_due_date = None
            bill.save()
 
        return Response(
            _bill_response("Purchase bill updated successfully", bill),
            status=http_status.HTTP_200_OK,
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# DELETE  (soft delete)
# ─────────────────────────────────────────────────────────────────────────────
class DeletePurchaseBillView(APIView):
    permission_classes = []
 
    def delete(self, request, id):
        bill = PurchaseBill.objects.filter(id=id, is_deleted=False).first()
        if not bill:
            return Response({"error": "Bill not found"}, status=404)
 
        with transaction.atomic():
            reverse_purchase_stock(bill)
            bill.is_deleted = True
            bill.save()
 
        return Response(
            {"message": "Purchase bill deleted successfully"},
            status=http_status.HTTP_200_OK,
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# GET SINGLE
# ─────────────────────────────────────────────────────────────────────────────
class GetPurchaseBillView(APIView):
    permission_classes = []
 
    def get(self, request, id):
        bill = PurchaseBill.objects.filter(id=id, is_deleted=False).first()
        if not bill:
            return Response({"error": "Bill not found"}, status=404)
 
        serializer = PurchaseBillSerializer(bill)
        return Response(serializer.data, status=http_status.HTTP_200_OK)
 

class HsnListCreateAPIView(APIView):
    permission_classes = []
    # GET - List all HSNs
    def get(self, request):
        queryset = HsnTable.objects.all().order_by("-created_at")
        serializer = HsnSerializer(queryset, many=True)
        return Response(serializer.data, status=http_status.HTTP_200_OK)

    # POST - Create new HSN
    def post(self, request):
        serializer = HsnSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                serializer.data,
                status=http_status.HTTP_201_CREATED
            )
        return Response(
            serializer.errors,
            status=http_status.HTTP_400_BAD_REQUEST
        )
# class OrderPaymentHistoryView(APIView):
#    permission_classes = []

#     def get(self, request, order_id):
#         order = Order.objects.filter(id=order_id).first()
#         if not order:
#             return Response({"error": "Order not found"}, status=404)

#         payments = order.payments.all().values()

#         return Response({
#             "order_id": order.id,
#             "total_amount": order.total_amount,
#             "total_paid": order.total_paid(),
#             "remaining_amount": order.remaining_amount(),
#             "payments": list(payments)
#         })


# Final order-bill endpoint used by the order details screen.
# An order stores one bill/payment record, so POST creates it once while
# PUT edits the same record and DELETE clears it for regeneration.
class UpdatePaymentDetailsOrderView(APIView):
    permission_classes = []

    def get_order(self, order_id):
        return Order.objects.filter(id=order_id, is_deleted=False).first()

    def bill_exists(self, order):
        return bool(
            order.payment_date
            or order.payment_method
            or order.transaction_id
            or order.paid_amount > Decimal("0.00")
        )

    def parse_amount(self, amount, default):
        if amount in (None, ""):
            return default
        try:
            amount = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Invalid amount")
        if amount < Decimal("0.00"):
            raise ValueError("Amount cannot be negative")
        return amount

    def parse_date(self, payment_date):
        if not payment_date:
            return timezone.now()
        for date_format in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(payment_date, date_format)
            except ValueError:
                continue
        raise ValueError("Invalid date format")

    def apply_details(self, order, request, default_amount):
        amount = self.parse_amount(request.data.get("amount"), default_amount)
        if amount > order.total_amount:
            raise ValueError("Amount exceeds order total")

        payment_method = request.data.get("payment_method", order.payment_method)
        allowed_methods = {choice[0] for choice in Order.PAYMENT_METHODS}
        if payment_method not in allowed_methods:
            raise ValueError("Invalid payment method")

        order.paid_amount = amount
        order.payment_method = payment_method
        order.transaction_id = request.data.get("transaction_id", order.transaction_id) or None
        order.payment_date = self.parse_date(request.data.get("payment_date"))
        order.update_payment_status()
        order.save(update_fields=[
            "paid_amount", "payment_method", "transaction_id",
            "payment_date", "paid_status",
        ])

    def response_data(self, order, message):
        return Response({
            "message": message,
            "order_id": order.id,
            "bill_generated": self.bill_exists(order),
            "paid_amount": str(order.paid_amount),
            "remaining_amount": str(order.remaining_amount()),
            "paid_status": order.paid_status,
            "payment_method": order.payment_method,
            "payment_date": order.payment_date,
            "transaction_id": order.transaction_id,
        })

    def post(self, request, order_id):
        try:
            order = self.get_order(order_id)
            if not order:
                return Response({"error": "Order not found"}, status=404)
            if self.bill_exists(order):
                return Response(
                    {"error": "Bill already generated. Use Edit Bill instead."},
                    status=409,
                )

            self.apply_details(order, request, Decimal("0.00"))
            return self.response_data(order, "Bill generated successfully")
        except ValueError as error:
            return Response({"error": str(error)}, status=400)
        except Exception as error:
            return Response({"error": str(error)}, status=500)

    def put(self, request, order_id):
        try:
            order = self.get_order(order_id)
            if not order:
                return Response({"error": "Order not found"}, status=404)
            if not self.bill_exists(order):
                return Response({"error": "Bill has not been generated yet"}, status=404)

            self.apply_details(order, request, order.paid_amount)
            return self.response_data(order, "Bill updated successfully")
        except ValueError as error:
            return Response({"error": str(error)}, status=400)
        except Exception as error:
            return Response({"error": str(error)}, status=500)

    patch = put

    def delete(self, request, order_id):
        order = self.get_order(order_id)
        if not order:
            return Response({"error": "Order not found"}, status=404)
        if not self.bill_exists(order):
            return Response({"error": "Bill has not been generated yet"}, status=404)

        order.paid_amount = Decimal("0.00")
        order.payment_method = None
        order.transaction_id = None
        order.payment_date = None
        order.update_payment_status()
        order.save(update_fields=[
            "paid_amount", "payment_method", "transaction_id",
            "payment_date", "paid_status",
        ])

        return self.response_data(order, "Bill deleted successfully")
