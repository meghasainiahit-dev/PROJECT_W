from rest_framework import serializers
from .models import *
from django.conf import settings
from django.core.files.storage import default_storage
import  os
from rest_framework import serializers
from django.db import transaction
from rest_framework import serializers
from rest_framework import status
from decimal import Decimal

from .inventory_utils import allocate_serials_for_order
from rest_framework import serializers
from .models import Vendor


class VendorSerializer(serializers.ModelSerializer):
    initials = serializers.SerializerMethodField()
    full_location = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = [
            "id",
            "name",
            "country_code",
            "mobile",
            "email",
            "address",
            "city",
            "state",
            "country",
            "pin_code",
            "with_Gst",
            "firm_name",
            "gst_number",
            "initials",
            "full_location",
        ]

    def get_initials(self, obj):
        return (obj.name[:2] or "VN").upper()

    def get_full_location(self, obj):
        return ", ".join([x for x in [obj.city, obj.state, obj.country] if x])

    def validate(self, data):
        instance = getattr(self, "instance", None)

        with_gst = data.get("with_Gst", getattr(instance, "with_Gst", False))
        firm_name = data.get("firm_name", getattr(instance, "firm_name", None))
        gst_number = data.get("gst_number", getattr(instance, "gst_number", None))

        if with_gst:
            if not firm_name:
                raise serializers.ValidationError({
                    "firm_name": "Firm name is required when GST is enabled."
                })
            if not gst_number:
                raise serializers.ValidationError({
                    "gst_number": "GST number is required when GST is enabled."
                })

        return data

class SalesChannelSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesChannel
        fields = '__all__'

# class ProductSerializer(serializers.ModelSerializer):
#     product_image = serializers.ImageField(required=False, allow_null=True)
#     product_image_variants_files = serializers.ListField(
#         child=serializers.ImageField(),
#         write_only=True,
#         required=False
#     )

#     class Meta:
#         model = Product
#         fields = "__all__"

#     def update(self, instance, validated_data):
#         request = self.context.get('request')
#         validated_data.pop('product_image_variants_files', None)

#         for attr, value in validated_data.items():
#             setattr(instance, attr, value)

#         files = request.FILES.getlist('product_image_variants_files')
#         if files:
#             existing = list(instance.product_image_variants or [])
#             for f in files:
#                 path = default_storage.save(f'product/variants/{f.name}', f)
#                 existing.append(path)
#             instance.product_image_variants = existing

#         instance.save()
#         return instance

#     def to_representation(self, instance):
#         data = super().to_representation(instance)
#         request = self.context.get('request')

#         if instance.product_image:
#             try:
#                 data['product_image'] = request.build_absolute_uri(
#                     instance.product_image.url
#                 )
#             except Exception:
#                 data['product_image'] = None

#         variants = []
#         for img in (instance.product_image_variants or []):
#             if img:
#                 try:
#                     full_url = f"{img}"
#                     variants.append(full_url)
#                 except Exception:
#                     pass
#         data['product_image_variants'] = variants

#         return data

from rest_framework import serializers
from django.conf import settings
from django.core.files.storage import default_storage
from .models import Product


class UploadedImagePathField(serializers.ImageField):
    def to_internal_value(self, data):
        if isinstance(data, str):
            media_url = getattr(settings, "MEDIA_URL", "/media/")
            if media_url in data:
                return data.split(media_url, 1)[1]
            if data.startswith(media_url):
                return data[len(media_url):]
            return data.lstrip("/")
        return super().to_internal_value(data)


class ProductSerializer(serializers.ModelSerializer):
    product_image = UploadedImagePathField(required=False, allow_null=True)
    product_image_variants = serializers.JSONField(required=False, default=list)

    class Meta:
        model = Product
        fields = "__all__"

    def update(self, instance, validated_data):
        request = self.context.get('request')

        # ✅ Main image tabhi update ho jab bheji jaye
        if 'product_image' not in request.data:
            validated_data.pop('product_image', None)

        # ✅ Variants: agar aaya hai to replace, nahi aaya to untouched
        if 'product_image_variants' in validated_data:
            instance.product_image_variants = validated_data.pop('product_image_variants')
        else:
            validated_data.pop('product_image_variants', None)

        # 🔹 Baaki normal fields update
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')

        # 🔹 Main image full URL
        if instance.product_image:
            try:
                data['product_image'] = request.build_absolute_uri(
                    instance.product_image.url
                )
            except Exception:
                data['product_image'] = None

        # 🔹 Variants as-is return karo (already JSON hai)
        data['product_image_variants'] = instance.product_image_variants or []

        return data
class InventorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Inventory
        fields = '__all__'



class DamageInventorySerializer(serializers.ModelSerializer):
    class Meta:
        model = DamageInventory
        fields = "__all__"

class OrderItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)

    class Meta:
        model = OrderItem
        fields = "__all__"

class OrderRemarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderRemark
        fields = ["id", "remark", "created_at"]
class OrderItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['product', 'quantity', 'unit_price']   # yeh fields POST karne ke liye
from django.db import transaction
class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    remarks = OrderRemarkSerializer(source="remarks_list", many=True, read_only=True)

    latest_status = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = "__all__"

    def get_latest_status(self, obj):
        status = (
            OrderStatus.objects
            .filter(order_id=obj.id)
            .order_by('-created_at')
            .first()
        )

        if status:
            return {
                "status": status.status,
                "note": status.json.get("note") if status.json else None,
                "created_at": status.created_at
            }
        return None



class OrderCreateSerializer(serializers.ModelSerializer):
    items = OrderItemCreateSerializer(many=True)
    
    # 🔥 MULTIPLE REMARKS SUPPORT
    remarks = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )

    class Meta:
        model = Order
        fields = [
            'channel',
            'customer_name',
            'customer_email',
            'country_code',
            'mobile',
            'remarks',
            'items',
            'channel_order_id',
            'package_expence',
            'buyer_shipment_charger',
            'buyer_tax_amount'
        ]

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        remarks_data = validated_data.pop('remarks', [])

        with transaction.atomic():

            order = Order.objects.create(
                total_amount=Decimal("0"),
                **validated_data
            )

            total_amount = Decimal("0")

            for item_data in items_data:
                product = item_data['product']
                quantity = item_data['quantity']
                unit_price = Decimal(str(item_data.get('unit_price', 0)))

                total_amount += unit_price * quantity

                try:
                    serials = allocate_serials_for_order(product, quantity, order)
                except ValueError as exc:
                    raise serializers.ValidationError({"stock_error": str(exc)})

                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price,
                )

                StockMovement.objects.create(
                    product=product,
                    delta=-quantity,
                    reason='ORDER',
                    channel=order.channel,
                    order=order,
                    condition='OK',
                    note=f"Order #{order.id} serials: {', '.join(serials)}"
                )

            # 🔥 SAVE MULTIPLE REMARKS
            for remark in remarks_data:
                OrderRemark.objects.create(
                    order=order,
                    remark=remark
                )

            tax = total_amount * Decimal("0.05")
            package_expence = Decimal(str(order.package_expence or 0))
            buyer_shipment_charger = Decimal(str(order.buyer_shipment_charger or 0))
            buyer_tax_amount = Decimal(str(order.buyer_tax_amount or 0))

            order.total_amount = (
                total_amount
                + tax
                + package_expence
                + buyer_shipment_charger
                + buyer_tax_amount
            )
            order.save(update_fields=["total_amount"])

            return order


class StockMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMovement
        fields = '__all__'


# --------- Return Serializer (for API Input) ---------
class ReturnSerializer(serializers.Serializer):
    order_id = serializers.IntegerField()
    channel_id = serializers.IntegerField()
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField()
    condition = serializers.ChoiceField(choices=StockMovement.CONDITION_CHOICES)
    
    
class ProductStockSerializer(serializers.ModelSerializer):
    # inventory_quantity = serializers.IntegerField(source='inventory.quantity', read_only = True )
    inventory_quantity = serializers.SerializerMethodField()
    class Meta:
        model = Product
        fields = ['name','sku','size','unit_purchase_price','inventory_quantity']
        
        
    def get_inventory_quantity(self,obj):
        if hasattr(obj,'inventory') and obj.inventory:
            return obj.inventory.quantity
        return 0
        
   
class HsnSerializer(serializers.ModelSerializer):
    class Meta:
        model = HsnTable
        fields = ["id", "hsn_code", "gst_percentage", "created_at"]


class LowStockSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(source="inventory.quantity")
    sku = serializers.CharField()
    name = serializers.CharField()

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "quantity",
        ]
        from rest_framework import serializers
from .models import PurchaseBill

# serializers.py mein sirf PurchaseBillSerializer replace karo
# Baaki serializers same rahenge

class PurchaseBillSerializer(serializers.ModelSerializer):
    vendor           = serializers.SerializerMethodField()
    items            = serializers.SerializerMethodField()
    subtotal         = serializers.SerializerMethodField()
    tax_amount       = serializers.SerializerMethodField()
    total_amount     = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()
    tax_fields       = serializers.SerializerMethodField()

    class Meta:
        model  = PurchaseBill
        fields = [
            "id",
            "bill_number",
            "bill_date",
            "place_of_supply",
            "vendor",

            # GST
            "gst_type",
            "tax_fields",        # with_gst → values, no_gst → False

            # Amounts
            "subtotal",
            "tax_amount",
            "discount",
            "shipping",
            "other_expense",
            "round_off",
            "total_amount",

            # Payment
            "paid_amount",
            "remaining_amount",
            "status",            # PAID / UNPAID / PARTIAL (auto-set)
            "payment_mode",
            "transaction_id",
            "paid_date",
            "payment_due_date",

            # Meta
            "description",
            "created_at",
            "items",
        ]

    def get_vendor(self, obj):
        return {
            "id":     obj.vendor.id,
            "name":   obj.vendor.name,
            "mobile": obj.vendor.mobile,
        }

    def get_tax_fields(self, obj):
        """
        with_gst → GST breakdown return karo
        no_gst   → False return karo
        """
        if obj.gst_type == "with_gst":
            return {
                "sgst_percent": float(obj.sgst_percent),
                "cgst_percent": float(obj.cgst_percent),
                "igst_percent": float(obj.igst_percent),
                "tax_amount":   float(self.get_tax_amount(obj)),
            }
        return False

    def get_subtotal(self, obj):
        item_subtotal = sum(
            (item.unit_price or Decimal("0.00")) * item.quantity
            for item in obj.items.all()
        )
        return float(item_subtotal or obj.subtotal or Decimal("0.00"))

    def get_tax_amount(self, obj):
        if obj.gst_type != "with_gst":
            return 0.0
        taxable_base = Decimal(str(self.get_subtotal(obj))) - (obj.discount or Decimal("0.00"))
        taxable_base = max(taxable_base, Decimal("0.00"))
        tax_percent = (
            (obj.sgst_percent or Decimal("0.00"))
            + (obj.cgst_percent or Decimal("0.00"))
            + (obj.igst_percent or Decimal("0.00"))
        )
        tax_amount = taxable_base * tax_percent / Decimal("100")
        return float(tax_amount.quantize(Decimal("0.01")))

    def get_total_amount(self, obj):
        taxable_base = Decimal(str(self.get_subtotal(obj))) - (obj.discount or Decimal("0.00"))
        taxable_base = max(taxable_base, Decimal("0.00"))
        total = (
            taxable_base
            + Decimal(str(self.get_tax_amount(obj)))
            + (obj.shipping or Decimal("0.00"))
            + (obj.other_expense or Decimal("0.00"))
            + (obj.round_off or Decimal("0.00"))
        )
        return float(max(total, Decimal("0.00")).quantize(Decimal("0.01")))

    def get_items(self, obj):
        items = []
        for item in obj.items.select_related("product").all():
            calculated_total = (item.unit_price or Decimal("0.00")) * item.quantity
            total_price = item.total_price if item.total_price else calculated_total
            items.append({
                "id":           item.id,
                "product_id":   item.product.id,
                "product_name": item.product.name,
                "product_sku":  item.product.sku,
                "quantity":     item.quantity,
                "unit_price":   float(item.unit_price),
                "total_price":  float(total_price),
            })
        return items

    def get_remaining_amount(self, obj):
        """Total - Paid (kabhi negative nahi)."""
        remaining = Decimal(str(self.get_total_amount(obj))) - (obj.paid_amount or Decimal("0.00"))
        return float(max(remaining, Decimal("0.00")))
class CourierReturnCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourierReturn
        fields = [
            "order",
            "product",
            "quantity",
            "condition",
            "claim_status",
            "claim_result",
            "claim_amount",
            "return_status",
            "return_amount",
            "return_charges",
            "return_receive_date",
            "return_photo",
            "return_video",
            "return_reason",
            "remarks",
        ]


class CourierReturnUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourierReturn
        fields = [
            "return_status",
            "return_amount",
            "return_charges",
            "return_receive_date",
            "return_photo",
            "return_video",
            "return_reason",
            "remarks",
        ]

    def validate(self, data):
        return_status = data.get("return_status")

        if return_status == "APPROVED":
            required_fields = [
                "return_amount",
                "return_charges",
                "return_receive_date",
                "return_reason",
            ]

            for field in required_fields:
                value = data.get(field) or getattr(self.instance, field, None)
                if not value:
                    raise serializers.ValidationError({
                        field: f"{field} is required when status is APPROVED"
                    })

        elif return_status == "NOT_APPROVED":
            data["return_amount"] = None
            data["return_charges"] = None
            data["return_receive_date"] = None
            data["return_photo"] = None
            data["return_video"] = None
            data["return_reason"] = None
            data["remarks"] = None

        elif return_status == "IN_PROGRESS":
            if not data.get("remarks") and not getattr(self.instance, "remarks", None):
                raise serializers.ValidationError({
                    "remarks": "Remarks is required when status is IN_PROGRESS"
                })

            data["return_amount"] = None
            data["return_charges"] = None
            data["return_receive_date"] = None
            data["return_photo"] = None
            data["return_video"] = None
            data["return_reason"] = None

        return data


class CourierReturnSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourierReturn
        fields = "__all__"

    def validate(self, data):
        condition = data.get("condition")
        claim_status = data.get("claim_status")
        claim_result = data.get("claim_result")
        claim_amount = data.get("claim_amount")
        remarks = data.get("remarks")

        if condition == "DAMAGED":
            if claim_status == "CLAIMED":
                if claim_result == "RECEIVED" and not claim_amount:
                    raise serializers.ValidationError({
                        "claim_amount": "Claim amount is required when claim is received"
                    })
            elif claim_status == "NOT_CLAIMED":
                if not remarks:
                    raise serializers.ValidationError({
                        "remarks": "Remarks are required when not claimed"
                    })

        return data


class CustomerReturnSerializerNew(serializers.ModelSerializer):
    order_id = serializers.IntegerField(write_only=True)
    product_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = CustomerReturnModels
        fields = "__all__"
        extra_kwargs = {
            "order": {"read_only": True},
            "product": {"read_only": True},
        }

    def create(self, validated_data):
        order_id = validated_data.pop("order_id")
        product_id = validated_data.pop("product_id")

        validated_data["order"] = Order.objects.get(id=order_id)
        validated_data["product"] = Product.objects.get(id=product_id)

        return super().create(validated_data)

        
class ProductUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            'vendor',
            'prefix_code',
            'name',
            'size',
            'color',
            'material',
            'unit_purchase_price',
            'desc',
            'weight_before',
            'weight_after',
            'hsn',
            'product_image',
            'product_image_variants',
        ]
        
class ImageUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()
    
class MediatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = MediatorModels
        fields = ["id", "title"]


class CourirPartnerSerializer(serializers.ModelSerializer):
    mediators = MediatorSerializer(many=True, required=False)

    class Meta:
        model = CourirPartnerModel
        fields = ["id", "title", "mediators"]

    def create(self, validated_data):
        mediators_data = validated_data.pop("mediators", [])
        title = (validated_data.get("title") or "").strip()
        courier = CourirPartnerModel.objects.filter(title__iexact=title).order_by("id").first()
        if not courier:
            courier = CourirPartnerModel.objects.create(title=title)

        for mediator in mediators_data:
            mediator_title = (mediator.get("title") or "").strip()
            if mediator_title and not courier.mediators.filter(title__iexact=mediator_title).exists():
                MediatorModels.objects.create(courier_partner=courier, title=mediator_title)

        return courier
class ShipmentSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source="order.id", read_only=True)

    class Meta:
        model = Shipment
        fields = "__all__"
class OrderStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderStatus
        fields = '__all__'
class ProductVariantImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model  = ProductVariantImage
        fields = ['id', 'image', 'image_url', 'is_primary', 'order']

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None

class ProductVariantSerializer(serializers.ModelSerializer):
    images = ProductVariantImageSerializer(many=True, read_only=True)
    size     = serializers.CharField(required=False, allow_blank=True, default='')
    material = serializers.CharField(required=False, allow_blank=True, default='')
    class Meta:
        model  = ProductVariant
        fields = ['id','size', 'material', 'price', 'images']
        # read_only_fields se 'product' hata do
        read_only_fields = []






from rest_framework import serializers
from .models import Order, OrderStatus, Shipment,MediatorModels
from .models import CourirPartnerModel

ORDER_STATUS_MAP = {
    1: "In Process",
    2: "Packed",
    3: "In Transit",
    4: "Delivered",
    5: "Cancelled",
    6: "Courier Return",
    7: "Customer Return",
    8: "Returned",
    9: "Returned",
}



class OrderListSerializer(serializers.ModelSerializer):
    date = serializers.SerializerMethodField()
    channel = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    order_status = serializers.SerializerMethodField()
    latest_status = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    remarks = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
        "id",
        "customer_name",
        "channel_order_id",
        "mobile",
        "country_code",
        "customer_email",
        "created_at",           # ✅ add
        "date",
        "channel",
        "status",
        "order_status",
        "latest_status",
        "total_amount",
        "package_expence",
        "buyer_shipment_charger",
        "buyer_tax_amount",
        "paid_amount",
        "refunded_amount",       # ✅ add
        "refund_additional_charges",  # ✅ add
        "paid_status",
        "payment_method",        # ✅ add
        "payment_date",          # ✅ add
        "transaction_id",        # ✅ add
        "is_deleted",
        "items",
        "remarks",
        ]
      

    def get_date(self, obj):
        return obj.created_at.date().isoformat() if obj.created_at else ""

    def get_channel(self, obj):
        return obj.channel.name if obj.channel else ""

    def get_latest_status(self, obj):
        # prefetched_statuses view se inject karega — nahi mila to DB hit
        statuses = getattr(obj, "_prefetched_statuses", None)
        if statuses is not None:
            latest = statuses[0] if statuses else None
        else:
            latest = (
                OrderStatus.objects
                .filter(order_id=obj.id)
                .order_by("-created_at")
                .first()
            )
        if not latest:
            return None
        note = ""
        if latest.json:
            note = latest.json.get("message") or latest.json.get("note") or ""
        return {
            "status": latest.status,
            "note": note,
            "created_at": latest.created_at,
        }

    def get_order_status(self, obj):
        statuses = getattr(obj, "_prefetched_statuses", None)
        if statuses is not None:
            latest = statuses[0] if statuses else None
        else:
            latest = (
                OrderStatus.objects
                .filter(order_id=obj.id)
                .order_by("-created_at")
                .first()
            )
        if latest:
            return latest.status
        return obj.order_status

    def get_status(self, obj):
        if obj.status == "CANCELLED":
            return "Cancelled"
        statuses = getattr(obj, "_prefetched_statuses", None)
        if statuses is not None:
            latest = statuses[0] if statuses else None
        else:
            latest = (
                OrderStatus.objects
                .filter(order_id=obj.id)
                .order_by("-created_at")
                .first()
            )
        code = latest.status if latest else obj.order_status
        return ORDER_STATUS_MAP.get(code, "Active")

    def get_items(self, obj):
        items = []
        for item in obj.items.all():
            product = item.product
            if not product:
                continue
            image = None
            if product.product_image_variants:
                image = product.product_image_variants[0]
            elif product.product_image:
                image = product.product_image.url
            items.append({
                "id": item.id,
                "product_id": product.id,
                "name": product.name,
                "sku": product.sku,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "product_image": image,
            })
        return items

    def get_remarks(self, obj):
        return [
            {
                "id": r.id,
                "remark": r.remark,
                "created_at": r.created_at,
            }
            for r in obj.remarks_list.all()
        ]

class OrderItemSerializer(serializers.Serializer):
    product_id = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    sku = serializers.SerializerMethodField()
    quantity = serializers.IntegerField()
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    subtotal = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    serial = serializers.SerializerMethodField()

    def get_product_id(self, obj):
        return obj.product_id

    def get_name(self, obj):
        return obj.product.name if obj.product else ""

    def get_sku(self, obj):
        return obj.product.sku if obj.product else ""

    def get_subtotal(self, obj):
        return obj.quantity * obj.unit_price

    def get_image(self, obj):
        if obj.product and obj.product.product_image:
            return obj.product.product_image.url
        return ""

    def get_serial(self, obj):
        unit = obj.product.units.filter(order=obj.order).first()
        if unit:
            return unit.serial_number
        return f"{obj.product.sku}-0001" if obj.product else ""


class OrderDetailSerializer(serializers.ModelSerializer):
    date = serializers.SerializerMethodField()
    channel = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    channel_id = serializers.SerializerMethodField()
    total_items = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    package = serializers.SerializerMethodField()
    shipment = serializers.SerializerMethodField()
    status_date = serializers.SerializerMethodField()
    remark_date = serializers.SerializerMethodField()
    remarks = serializers.SerializerMethodField()
    bill_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "date",
            "customer_name",
            "mobile",
            "email",
            "channel",
            "channel_id",
            "total_items",
            "total_amount",
            "package_expence",
            "buyer_shipment_charger",
            "buyer_tax_amount",
            "order_status",
            "status",
            "status_date",
            "remark_date",
            "remarks",
            "items",
            "package",
            "shipment",
            "bill_breakdown",
        ]

    def get_date(self, obj):
        return obj.created_at.date().isoformat() if obj.created_at else ""

    def get_channel(self, obj):
        return obj.channel.name if obj.channel else ""

    def get_status(self, obj):
        if obj.status == "CANCELLED":
            return "Cancelled"
        return ORDER_STATUS_MAP.get(obj.order_status, "Active")

    def get_email(self, obj):
        return obj.customer_email or ""

    def get_channel_id(self, obj):
        return obj.channel_order_id or ""

    def get_total_items(self, obj):
        return obj.total_items

    def get_items(self, obj):
        return OrderItemSerializer(obj.items.all(), many=True).data

    def get_remarks(self, obj):
        return [
            {
                "id": remark.id,
                "remark": remark.remark,
                "created_at": (
                    remark.created_at.strftime("%d %b %Y, %I:%M %p")
                    if remark.created_at
                    else ""
                ),
            }
            for remark in obj.remarks_list.order_by("-created_at")
        ]

    def get_bill_breakdown(self, obj):
        items_total = sum(
            (item.unit_price or Decimal("0.00")) * item.quantity
            for item in obj.items.all()
        )
        product_tax_percent = Decimal("5.00")
        product_tax = (items_total * product_tax_percent / Decimal("100")).quantize(Decimal("0.01"))
        package_expence = obj.package_expence or Decimal("0.00")
        buyer_shipping = obj.buyer_shipment_charger or Decimal("0.00")
        buyer_tax = obj.buyer_tax_amount or Decimal("0.00")
        calculated_total = (
            items_total
            + product_tax
            + package_expence
            + buyer_shipping
            + buyer_tax
        ).quantize(Decimal("0.01"))
        printed_total = (obj.total_amount or calculated_total).quantize(Decimal("0.01"))
        adjustment = (printed_total - calculated_total).quantize(Decimal("0.01"))

        return {
            "items_total": float(items_total),
            "product_tax_percent": float(product_tax_percent),
            "product_tax": float(product_tax),
            "package_expence": float(package_expence),
            "buyer_shipment_charger": float(buyer_shipping),
            "buyer_tax_amount": float(buyer_tax),
            "calculated_total": float(calculated_total),
            "other_adjustment": float(adjustment),
            "printed_amount": float(printed_total),
            "grand_total": float(printed_total),
        }

    def get_package(self, obj):
        item = obj.items.select_related("product").first()
        product = item.product if item else None

        package = {
            "height": product.height or "",
            "width": product.width or "",
            "length": product.length or "",
            "dead_weight": product.weight_before or "",
            "vol_weight": product.weight_after or "",
            "billed_weight": product.weight_after or product.weight_before or "",
        } if product else {}

        if any(package.values()):
            return package

        packed_status = (
            OrderStatus.objects
            .filter(order_id=obj.id, status=2)
            .order_by("-created_at")
            .first()
        )
        status_package = (packed_status.json or {}).get("package") if packed_status else None
        return status_package or package

    def get_shipment(self, obj):
        shipment = obj.shipments.select_related(
            "courier_partner",
            "mediator",
        ).first()

        if not shipment:
            return {}

        return {
            "courier": shipment.courier_partner.title if shipment.courier_partner else "",
            "mediator": shipment.mediator.title if shipment.mediator else "",
            "tracking_id": shipment.tracking_id,
            "ship_date": shipment.shipping_date.strftime("%d %b %Y") if shipment.shipping_date else "",
            "shipping_expense": shipment.shipping_expense,
            "tracking_url": shipment.tracking_url or "",
        }

    def get_status_date(self, obj):
        status_obj = OrderStatus.objects.filter(order_id=obj.id).order_by("-created_at").first()
        return status_obj.created_at.strftime("%d/%m/%Y - %H:%M") if status_obj else ""

    def get_remark_date(self, obj):
        remark = obj.remarks_list.order_by("-created_at").first()
        return remark.created_at.strftime("%d %b %Y, %I:%M %p") if remark else ""

class CourierPartnerSerializer(serializers.ModelSerializer):
    mediators = MediatorSerializer(many=True, required=False)

    class Meta:
        model = CourirPartnerModel
        fields = ["id", "title", "mediators"]

    def create(self, validated_data):
        mediators_data = validated_data.pop("mediators", [])
        title = (validated_data.get("title") or "").strip()
        courier = CourirPartnerModel.objects.filter(title__iexact=title).order_by("id").first()
        if not courier:
            courier = CourirPartnerModel.objects.create(title=title)
        for mediator_data in mediators_data:
            mediator_title = (mediator_data.get("title") or "").strip()
            if mediator_title and not courier.mediators.filter(title__iexact=mediator_title).exists():
                MediatorModels.objects.create(courier_partner=courier, title=mediator_title)
        return courier

class ShipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shipment
        fields = "__all__"


class OrderStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderStatus
        fields = "__all__"
