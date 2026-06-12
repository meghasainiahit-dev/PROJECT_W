
from django.shortcuts import get_object_or_404
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
from rest_framework import serializers
from ..inventory_utils import get_printable_serials


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = "__all__"
class InventorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Inventory
        fields = "__all__"
class DamageInventorySerializer(serializers.ModelSerializer):
    class Meta:
        model = DamageInventory
        fields = "__all__"
class ProductSerializer(serializers.ModelSerializer):
    vendor = VendorSerializer()
    inventory = InventorySerializer()
    damaged_inventory = DamageInventorySerializer(many=True)

    class Meta:
        model = Product
        fields = "__all__"

class OrderBarcodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderBarcode
        fields = "__all__"

class GenerateBulkBarcode(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        product_id = request.data.get("product_id")
        qty        = request.data.get("quantity")

        if not product_id:
            return Response({"error": "product_id required"}, status=400)

        product = get_object_or_404(Product, id=product_id)

        if not hasattr(product, "inventory"):
            return Response({"error": "Inventory not found for this product"}, status=400)

        # ── in_stock serials fetch karo ────────────────────────────────────
        qty = int(qty) if qty else None

        in_stock_units = (
            ProductUnit.objects
            .filter(product=product, status="in_stock")
            .order_by("serial_number")
        )

        total_available = in_stock_units.count()

        if total_available == 0:
            return Response({
                "error": "Koi bhi in_stock serial available nahi hai."
            }, status=400)

        if qty and qty > total_available:
            return Response({
                "error": f"Requested {qty} but only {total_available} available in stock."
            }, status=400)

        # qty diya to utne lo, nahi diya to sab lo
        if qty:
            in_stock_units = in_stock_units[:qty]

        # ── barcode images generate karo (stock change nahi hoga) ─────────
        barcodes_dir = os.path.join(settings.MEDIA_ROOT, "barcodes")
        os.makedirs(barcodes_dir, exist_ok=True)

        result = []
        for unit in in_stock_units:
            file_name = f"{unit.serial_number}.png"
            file_path = os.path.join(barcodes_dir, file_name)

            # Image pehle se bani ho to dobara mat banao
            if not os.path.exists(file_path):
                code128 = barcode.get("code128", unit.serial_number, writer=ImageWriter())
                buffer  = BytesIO()
                code128.write(buffer)
                with open(file_path, "wb") as f:
                    f.write(buffer.getvalue())

            image_url = request.build_absolute_uri(
                f"{settings.MEDIA_URL}barcodes/{file_name}"
            )

            result.append({
                "serial_number": unit.serial_number,
                "barcode_image": image_url,
            })

        return Response({
            "product_id":      product.id,
            "product_name":    product.name,
            "product_sku":     product.sku,
            "total_available": total_available,
            "returned_count":  len(result),
            "remaining_stock": product.inventory.quantity,  # stock change nahi hua
            "serials":         result,
        })
# class GenerateBulkBarcode(APIView):
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         product_id = request.data.get("product_id")
#         qty = int(request.data.get("quantity", 1))

#         product = get_object_or_404(Product, id=product_id)

#         # ✅ Ensure inventory exists
#         if not hasattr(product, "inventory"):
#             return Response({"error": "Inventory not found for this product"}, status=400)

#         inventory = product.inventory

#         # ❌ Stop if not enough stock
#         if inventory.quantity < qty:
#             return Response({
#                 "error": f"Not enough stock. Available: {inventory.quantity}"
#             }, status=400)

#         # ✅ Base SKU (without last serial)
#         base_sku = "-".join(product.sku.split("-")[:-1])

#         last_serial = product.serial or 0

#         barcodes = []

#         barcodes_dir = os.path.join(settings.MEDIA_ROOT, "barcodes")
#         os.makedirs(barcodes_dir, exist_ok=True)

#         for i in range(qty):
#             new_serial = last_serial + i + 1
#             serial_code = str(new_serial).zfill(5)

#             full_barcode = f"{base_sku}-{serial_code}"

#             code128 = barcode.get("code128", full_barcode, writer=ImageWriter())
#             buffer = BytesIO()
#             code128.write(buffer)

#             file_name = f"{full_barcode}.png"
#             file_path = os.path.join(barcodes_dir, file_name)

#             with open(file_path, "wb") as f:
#                 f.write(buffer.getvalue())

#             image_url = request.build_absolute_uri(
#                 f"{settings.MEDIA_URL}barcodes/{file_name}"
#             )

#             barcodes.append({
#                 "barcode": full_barcode,
#                 "image": image_url
#             })

#         # ✅ Reduce inventory stock
#         inventory.quantity -= qty
#         inventory.save()

#         # ✅ Update product serial (global counter)
#         product.serial = last_serial + qty
#         product.save()

#         return Response({
#             "barcodes": barcodes,
#             "remaining_stock": inventory.quantity
#         })

class ScanBarcode(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        barcode_value = request.query_params.get("barcode")

        if not barcode_value:
            return Response({"error": "Barcode is required"}, status=400)

        parts = barcode_value.split("-")

        if len(parts) < 2:
            return Response({"error": "Invalid barcode format"}, status=400)

        # ✅ Last part is serial, everything before it is base SKU.
        sku_without_serial = "-".join(parts[:-1])
        serial = parts[-1]

        # ✅ Find product by BASE SKU (works for all generated barcodes)
        product = (
            Product.objects.filter(sku=barcode_value).first()
            or get_object_or_404(Product, sku__startswith=sku_without_serial)
        )

        serializer = ProductSerializer(product)

        return Response({
            "barcode_scanned": barcode_value,
            "base_sku": sku_without_serial,
            "serial_scanned": serial,
            "product": serializer.data,
            "stock_left": product.inventory.quantity if hasattr(product, "inventory") else 0
        }, status=200)
class GenerateOrderBarcodes(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        order_id = request.data.get("order_id")
        product_id = request.data.get("product_id")

        order = get_object_or_404(Order, id=order_id)
        product = get_object_or_404(Product, id=product_id)

        # Ensure inventory exists
        if not hasattr(product, "inventory"):
            return Response({"error": "Inventory not found"}, status=400)

        inventory = product.inventory

        # Get ordered quantity from OrderItem
        try:
            order_item = OrderItem.objects.get(order=order, product=product)
        except OrderItem.DoesNotExist:
            return Response({"error": "This product is not in this order"}, status=400)

        qty = order_item.quantity

        # Check if barcodes already generated for this order
        existing = OrderBarcode.objects.filter(order=order, product=product)

        if existing.exists():
            # Return same barcodes again (FIXED per order)
            serializer = OrderBarcodeSerializer(existing, many=True)
            return Response({
                "order_id": order.id,
                "already_generated": True,
                "barcodes": serializer.data
            })

        # Check stock
        if inventory.quantity < qty:
            return Response({
                "error": f"Not enough stock. Available: {inventory.quantity}"
            }, status=400)

        # Base SKU without serial
        base_sku = "-".join(product.sku.split("-")[:-1])

        last_serial = product.serial or 0

        new_barcodes = []

        for i in range(qty):
            new_serial = last_serial + i + 1
            serial_code = str(new_serial).zfill(5)
            full_barcode = f"{base_sku}-{serial_code}"

            obj = OrderBarcode.objects.create(
                order=order,
                product=product,
                barcode=full_barcode,
                serial=new_serial
            )

            new_barcodes.append(obj)

        # Reduce inventory
        inventory.quantity -= qty
        inventory.save()

        # Update product serial counter
        product.serial = last_serial + qty
        product.save()

        serializer = OrderBarcodeSerializer(new_barcodes, many=True)

        return Response({
            "order_id": order.id,
            "barcodes": serializer.data,
            "remaining_stock": inventory.quantity
        })

class GetOrderBarcodes(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id, product_id):
        order = get_object_or_404(Order, id=order_id)
        product = get_object_or_404(Product, id=product_id)

        barcodes = OrderBarcode.objects.filter(order=order, product=product).order_by("serial")

        if not barcodes.exists():
            return Response({"error": "No barcodes generated for this order"}, status=404)

        serializer = OrderBarcodeSerializer(barcodes, many=True)

        return Response({
            "order_id": order.id,
            "product_id": product.id,
            "barcodes": serializer.data
        })
class GetAllOrderBarcodes(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        order = get_object_or_404(Order, id=order_id)

        barcodes = (
            OrderBarcode.objects
            .filter(order=order)
            .select_related("product")
            .order_by("product_id", "serial")
        )

        if not barcodes.exists():
            return Response(
                {"error": "No barcodes found for this order"},
                status=404
            )

        result = {}
        for b in barcodes:
            pid = b.product.id

            if pid not in result:
                result[pid] = {
                    "product_id": pid,
                    "product_name": b.product.name,
                    "barcodes": []
                }

            result[pid]["barcodes"].append({
                "barcode": b.barcode,
                "serial": b.serial
            })

        return Response({
            "order_id": order.id,
            "barcodes": list(result.values())
        })
