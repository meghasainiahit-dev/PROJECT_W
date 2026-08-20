from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
import barcode
from barcode.writer import ImageWriter
from io import BytesIO
from django.core.files import File
from decimal import Decimal


class UserAccessProfile(models.Model):
    ROLE_SUPER_ADMIN = "super_admin"
    ROLE_ADMIN = "admin"
    ROLE_USER = "user"

    ROLE_CHOICES = [
        (ROLE_SUPER_ADMIN, "Super Admin"),
        (ROLE_ADMIN, "Admin"),
        (ROLE_USER, "User"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="access_profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_USER)
    modules = models.JSONField(default=list, blank=True)
    action_permissions = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def has_module(self, module_key):
        if self.role == self.ROLE_SUPER_ADMIN or self.user.is_superuser:
            return True
        return module_key in (self.modules or [])

    def has_action(self, module_key, action):
        if self.role == self.ROLE_SUPER_ADMIN or self.user.is_superuser:
            return True
        return action in (self.action_permissions or {}).get(module_key, [])

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"

class Vendor(models.Model):
    name = models.CharField(max_length=120)
    country_code= models.CharField(max_length=10,default="+91")
    mobile = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100, blank=True, null=True)
    pin_code = models.CharField(max_length=10)
    with_Gst = models.BooleanField(default = False)
    firm_name = models.CharField(max_length=100,blank=True, null=True)
    gst_number = models.CharField(max_length=400,blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.city}, {self.country})"


class SalesChannel(models.Model):
    name = models.CharField(max_length=80, unique=True)
     
    def __str__(self):
        return self.name

class Order(models.Model):
    PAYMENT_METHODS = [
        ("NET_BANKING", "Net Banking"),
        ("UPI", "UPI"),
        ("CASH", "Cash"),
    ]
    ORDER_STATUS = [
        ("ACTIVE", "Active"),
        ("CANCELLED", "Cancelled"),
    ]
    status = models.CharField(
    max_length=20,
    choices=ORDER_STATUS,
    default="ACTIVE"
    )
    order_status = models.IntegerField(default=1)
    # 🔥 FIX: default added
    package_expence = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    buyer_shipment_charger = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    buyer_tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refund_additional_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)


    channel = models.ForeignKey("SalesChannel", on_delete=models.PROTECT, related_name='orders')

    customer_email = models.EmailField(blank=True, null=True)
    country_code = models.CharField(max_length=10)
    mobile = models.CharField(max_length=20, blank=True, null=True)
    customer_name = models.CharField(max_length=120, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    
    channel_order_id = models.CharField(max_length=225, blank=True, null=True)

    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, blank=True, null=True)

    # 🔥 FIXED datatype
    payment_date = models.DateTimeField(blank=True, null=True)

    paid_status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", "Pending"),
            ("PARTIAL", "Partial"),
            ("PAID", "Paid"),
        ],
        default="PENDING"
    )
    is_deleted = models.BooleanField(default=False)

    transaction_id = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Order #{self.pk}"

    @property
    def total_items(self):
        return sum(oi.quantity for oi in self.items.all())

    # 🔥 FIXED
    def total_paid(self):
        return self.paid_amount

    def remaining_amount(self):
        return self.total_amount - self.paid_amount

    def update_payment_status(self):
        if self.paid_amount >= self.total_amount:
            self.paid_status = "PAID"
        elif self.paid_amount > 0:
            self.paid_status = "PARTIAL"
        else:
            self.paid_status = "PENDING"

class OrderRemark(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="remarks_list")
    remark = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order {self.order.id} - {self.remark[:20]}"



# class StockMovement(models.Model):
#     REASON_CHOICES = [
#         ('ORDER', 'Order'),
#         ('PURCHASE', 'Purchase'),
#         ('RETURN', 'Return'),
#         ('ADJUST', 'Manual Adjust'),
#     ]
#     product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='movements')
#     delta = models.IntegerField()
#     reason = models.CharField(max_length=10, choices=REASON_CHOICES)
#     channel = models.ForeignKey(SalesChannel, null=True, blank=True, on_delete=models.SET_NULL)
#     order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL)
#     note = models.CharField(max_length=255, blank=True)
#     created_at = models.DateTimeField(auto_now_add=True)

#     class Meta:
#         ordering = ['-created_at']

#     def __str__(self):
#         return f"{self.product.sku} {self.delta} ({self.reason})"


#===================================Damage==========================






class GSTTable(models.Model):
    gst_percentage = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']
    def __str__(self):
        return f"All Products percentage - {self.gst_percentage}%"


# models.py mein sirf PurchaseBill model update karna hai
# Baaki sab same rahega — sirf yeh model replace karo

class PurchaseBill(models.Model):

    GST_TYPE_CHOICES = [
        ("with_gst", "With GST"),
        ("no_gst",   "No GST"),
    ]

    STATUS_CHOICES = [
        ("PAID",    "Paid"),
        ("UNPAID",  "Unpaid"),
        ("PARTIAL", "Partial"),
    ]

    PAYMENT_MODE_CHOICES = [
        ("cash",          "Cash"),
        ("bank_transfer", "Bank Transfer / NEFT / RTGS"),
        ("upi",           "UPI"),
    ]

    vendor          = models.ForeignKey("Vendor", on_delete=models.CASCADE, related_name="purchase_bills")
    bill_number     = models.CharField(max_length=120, unique=True)
    bill_date       = models.DateField()

    place_of_supply = models.CharField(max_length=100, blank=True, null=True)

    # ── GST ──────────────────────────────────────────────────────────────────
    gst_type        = models.CharField(
                          max_length=20,
                          choices=GST_TYPE_CHOICES,
                          default="with_gst"
                      )
    # tax_type REMOVED — gst_type hi kaafi hai
    sgst_percent    = models.DecimalField(max_digits=5,  decimal_places=2, default=0)
    cgst_percent    = models.DecimalField(max_digits=5,  decimal_places=2, default=0)
    igst_percent    = models.DecimalField(max_digits=5,  decimal_places=2, default=0)

    # ── Amounts ───────────────────────────────────────────────────────────────
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount      = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount        = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping        = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    other_expense   = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    round_off       = models.DecimalField(max_digits=5,  decimal_places=2, default=0)
    total_amount    = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Payment ───────────────────────────────────────────────────────────────
    paid_amount     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_date       = models.DateField(blank=True, null=True)
    payment_due_date = models.DateField(blank=True, null=True)

    status          = models.CharField(
                          max_length=20,
                          choices=STATUS_CHOICES,
                          default="UNPAID"
                      )
    payment_mode    = models.CharField(
                          max_length=20,
                          choices=PAYMENT_MODE_CHOICES,
                          blank=True, null=True
                      )
    transaction_id  = models.CharField(max_length=100, blank=True, null=True)

    # ── Meta ──────────────────────────────────────────────────────────────────
    description     = models.TextField(blank=True, null=True)
    is_deleted      = models.BooleanField(default=False)
    created_at      = models.DateTimeField(auto_now_add=True)

    # ── Methods ───────────────────────────────────────────────────────────────
    def remaining_amount(self):
        """Total se paid minus — kabhi negative nahi."""
        from decimal import Decimal
        remaining = self.total_amount - (self.paid_amount or Decimal("0.00"))
        return max(remaining, Decimal("0.00"))

    def update_payment_status(self):
        """Manually call karna ho to use karo — views mein calculate_purchase_totals se auto hota hai."""
        from decimal import Decimal
        if self.paid_amount >= self.total_amount:
            self.status = "PAID"
        elif self.paid_amount > Decimal("0.00"):
            self.status = "PARTIAL"
        else:
            self.status = "UNPAID"

    def __str__(self):
        return self.bill_number
    


class HsnTable(models.Model):
    hsn_code = models.CharField(max_length=12, blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True)
    gst_percentage = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    def __str__(self):
        return self.hsn_code

class Product(models.Model):
    vendor = models.ForeignKey("Vendor", on_delete=models.CASCADE, related_name="products")
    prefix_code = models.CharField(max_length=20, blank=True, null=True)
    name = models.CharField(max_length=150)
    size = models.CharField(max_length=50, blank=True)
    color = models.CharField(max_length=50, blank=True)
    material = models.CharField(max_length=50, blank=True)
    serial = models.BigIntegerField(blank=True, null=True)
    sku = models.CharField(max_length=150, unique=True, blank=True)
    barcode = models.CharField(max_length=150, unique=True, blank=True, null=True)
    barcode_image = models.ImageField(upload_to="barcodes/", blank=True, null=True)
    product_image = models.ImageField(upload_to="product/", blank=True, null=True)
    product_image_variants = models.JSONField(default=list, blank=True)
    unit_purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=00.00)
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, default=00.00)
    retailer_price = models.DecimalField(max_digits=10, decimal_places=2, default=00.00)
    desc = models.CharField(max_length=500, null=True)
    weight_before = models.CharField(max_length=120, blank=True, null=True)
    weight_after = models.CharField(max_length=120, blank=True, null=True)
    length  = models.CharField(max_length=120, blank=True, null=True)
    unit = models.CharField(max_length=120, blank=True, null=True)
    width = models.CharField(max_length=120, blank=True, null=True)
    height = models.CharField(max_length=120, blank=True, null=True)
    
    hsn = models.ForeignKey(
        HsnTable,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    class Meta:
        unique_together = (("vendor", "name", "size", "color", "material"),)

    def _sku_segment(self, value, default="NA", max_len=None):
        text = str(value or "").strip().upper()
        text = " ".join(text.split())
        text = text.replace("/", "").replace("\\", "").replace("_", " ")
        text = text.replace("--", "-").strip("- ")
        if not text:
            text = default
        return text[:max_len] if max_len else text

    def _sku_dimensions(self):
        if self.size:
            return self._sku_segment(self.size)

        parts = [
            self._sku_segment(value, "")
            for value in (self.length, self.width, self.height)
            if str(value or "").strip()
        ]
        if not parts:
            return "NA"

        dimensions = " X ".join(parts)
        unit = self._sku_segment(self.unit, "")
        return f"{dimensions} {unit}".strip()

    def _sku_name_code(self):
        words = [
            word
            for word in self._sku_segment(self.name, "").replace("-", " ").split()
            if word
        ]
        if not words:
            return "NA"
        if len(words) == 1:
            return words[0][:4]
        return "".join(word[0] for word in words[:4])[:4]

    # In Product.save() — replace the existing method with this cleaner version
    # =========================================================================================
    def save(self, *args, **kwargs):
        # ── 1. Auto serial per vendor (used only for SKU generation) ──────────
        if not self.serial:
            last = (
                Product.objects
                .filter(vendor=self.vendor)
                .aggregate(max_serial=models.Max("serial"))
                .get("max_serial") or 0
            )
            self.serial = last + 1

        # ── 2. Auto SKU (only on first save) ──────────────────────────────────
        if not self.sku:
            prefix = self._sku_segment(self.prefix_code, "GEN")
            hsn_code = self._sku_segment(getattr(self.hsn, "hsn_code", ""), "")
            product_code = hsn_code or self._sku_name_code()
            vendor_code = self._sku_segment(getattr(self.vendor, "name", ""), "NA", 2)
            name_code = self._sku_name_code()
            color_code = self._sku_segment(self.color, "NA", 2)
            size_code = self._sku_dimensions()
            material_code = self._sku_segment(self.material, "NA", 2)
            serial_code = str(self.serial).zfill(5)
            self.sku = "-".join([
                prefix,
                product_code,
                vendor_code,
                name_code,
                color_code,
                size_code,
                material_code,
                serial_code,
            ])

        # ── 3. Barcode = SKU, always fixed, never serial-based ────────────────
        if not self.barcode:           # set once, never overwritten
            self.barcode = self.sku

        # ── 4. Generate barcode image once ────────────────────────────────────
        if not self.barcode_image:
            code128 = barcode.get("code128", self.barcode, writer=ImageWriter())
            buffer  = BytesIO()
            code128.write(buffer)
            self.barcode_image.save(f"{self.sku}.png", File(buffer), save=False)

        super().save(*args, **kwargs)
    # =========================================================================================
    # def save(self, *args, **kwargs):

    #     # 🔹 Auto serial per vendor
    #     if not self.serial:
    #         last_serial = (
    #             Product.objects.filter(vendor=self.vendor)
    #             .aggregate(max_serial=models.Max("serial"))
    #             .get("max_serial") or 0
    #         )
    #         self.serial = last_serial + 1

    #     # 🔹 Auto SKU (only first time)
    #     if not self.sku:
    #         prefix = self.prefix_code.upper() if self.prefix_code else "GEN"
    #         brand_code = self.vendor.name[:2].upper()
    #         product_code = self.name[:2].upper()
    #         color_code = self.color[:2].upper() if self.color else "NA"
    #         size_code = self.size.upper() if self.size else "NA"
    #         material_code = self.material[:2].upper() if self.material else "NA"
    #         serial_code = str(self.serial).zfill(5)

    #         self.sku = f"{prefix}-{brand_code}-{product_code}-{color_code}-{size_code}-{material_code}-{serial_code}"

    #     # 🔹 Barcode = SKU (default)
    #     self.barcode = self.sku

    #     # 🔹 Preserve old barcode (important)
    #     if self.pk:
    #         old = Product.objects.filter(pk=self.pk).first()
    #         if old and old.barcode:
    #             self.barcode = old.barcode

    #     # 🔹 Generate barcode image only once
    #     if not self.barcode_image:
    #         code128 = barcode.get("code128", self.barcode, writer=ImageWriter())
    #         buffer = BytesIO()
    #         code128.write(buffer)
    #         self.barcode_image.save(f"{self.sku}.png", File(buffer), save=False)

    #     super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.sku}) ({self.id})"

class ProductVariant(models.Model):
    size     = models.CharField(max_length=50, blank=True)
    material = models.CharField(max_length=50, blank=True)
    price    = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        unique_together = (("size", "material"),)
        ordering = ["size"]

    def __str__(self):
        return f" {self.size} | {self.material}"


class ProductVariantImage(models.Model):
    variant    = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="images")
    image      = models.ImageField(upload_to="product_variants/")
    is_primary = models.BooleanField(default=False)
    order      = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"Variant {self.variant.id} - img {self.order}"    
class PurchaseBillItem(models.Model):
    bill = models.ForeignKey(PurchaseBill, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)

    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        old_quantity = 0
        old_product_id = None
        if self.pk:
            old_item = (
                PurchaseBillItem.objects
                .filter(pk=self.pk)
                .values("product_id", "quantity")
                .first()
            )
            if old_item:
                old_quantity = old_item["quantity"] or 0
                old_product_id = old_item["product_id"]

        self.price = self.unit_price
        self.total_price = self.quantity * self.unit_price
        self.amount = self.total_price

        super().save(*args, **kwargs)

        if old_product_id and old_product_id != self.product_id:
            old_inventory = Inventory.objects.filter(product_id=old_product_id).first()
            if old_inventory:
                old_inventory.quantity = max(0, old_inventory.quantity - old_quantity)
                old_inventory.save()
            inventory, created = Inventory.objects.get_or_create(product=self.product)
            inventory.quantity += self.quantity
            inventory.save()
            return

        diff = self.quantity - old_quantity
        if not diff:
            return
        
        inventory, created = Inventory.objects.get_or_create(product=self.product)
        inventory.quantity = max(0, inventory.quantity + diff)
        inventory.save()
    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    
class DamageInventory(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="damaged_inventory")
    quantity = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Damaged - {self.product.sku}: {self.quantity}"

class StockMovement(models.Model):
    REASON_CHOICES = [
        ('ORDER', 'Order'),
        ('PURCHASE', 'Purchase'),
        ('RETURN', 'Customer Return'),
        ('WPS', 'Warehouse Return'),
        ('ADJUST', 'Manual Adjust'),
    ]

    CONDITION_CHOICES = [
        ('OK', 'Product OK'),
        ('DAMAGED', 'Product Damaged'),
        ('LOST', 'Product Lost'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='movements')
    delta = models.IntegerField()  # +ve for add, -ve for remove
    reason = models.CharField(max_length=10, choices=REASON_CHOICES)
    condition = models.CharField(max_length=10, choices=CONDITION_CHOICES, blank=True, null=True)
    channel = models.ForeignKey(SalesChannel, null=True, blank=True, on_delete=models.SET_NULL)
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.product.sku} {self.delta} ({self.reason}) - {self.condition}"
    


class Inventory(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='inventory')
    quantity = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.product.sku}: {self.quantity}"


# Add this to models.py (after the Inventory model) ================================================

class ProductUnit(models.Model):
    """
    One row per physical unit of a product.
    Serial format: {SKU}-0001, {SKU}-0002, ...
    """
    STATUS_CHOICES = [
        ("in_stock", "In Stock"),
        ("sold",     "Sold"),
        ("reserved", "Reserved"),
        ("damaged",  "Damaged"),
    ]

    product       = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="units"
    )
    serial_number = models.CharField(max_length=200, unique=True)
    status        = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="in_stock", db_index=True
    )
    order         = models.ForeignKey(
        Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="product_units"
    )
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["serial_number"]
        indexes  = [
            models.Index(fields=["product", "status"]),
        ]

    def __str__(self):
        return f"{self.serial_number} [{self.status}]"
    
#================================================================================================

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='order_items')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.product.sku} x {self.quantity}"
 
class CourierReturn(models.Model):
    RETURN_CONDITION = [
        ("DAMAGED", "Damaged"),
        ("SAFE", "Safe"),
    ]
    CLAIM_STATUS = [
        ("CLAIMED", "Claimed"),
        ("NOT_CLAIMED", "Not Claimed"),
    ]
    CLAIM_RESULT = [
        ("RECEIVED", "Claim Received"),
        ("REJECTED", "Claim Rejected"),
    ]
    RETURN_STATUS = [
        ("IN_PROGRESS", "In Progress"),
        ("APPROVED", "Approved"),
        ("NOT_APPROVED", "Not Approved"),
    ]
    RETURN_REASON = [
        ("AGENT_ERROR", "Agent Error"),
        ("LACK_OF_STOCK", "Lack of Stock"),
        ("CUSTOMER_ERROR", "Customer Error"),
    ]

    order     = models.ForeignKey(Order, on_delete=models.CASCADE)
    product   = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity  = models.PositiveIntegerField()
    condition = models.CharField(max_length=10, choices=RETURN_CONDITION)

    claim_status  = models.CharField(max_length=20, choices=CLAIM_STATUS, blank=True, null=True)
    claim_result  = models.CharField(max_length=20, choices=CLAIM_RESULT, blank=True, null=True)
    claim_amount  = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    received_at = models.DateTimeField(auto_now_add=True)

    # ✅ Status
    return_status = models.CharField(
        max_length=20,
        choices=RETURN_STATUS,
        default="IN_PROGRESS"
    )

    # ✅ APPROVED fields
    return_amount       = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    return_charges      = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    return_receive_date = models.DateField(blank=True, null=True)
    return_photo        = models.ImageField(upload_to="courier_returns/photos/", blank=True, null=True)
    return_video        = models.FileField(upload_to="courier_returns/videos/", blank=True, null=True)
    return_reason       = models.CharField(max_length=20, choices=RETURN_REASON, blank=True, null=True)

    # ✅ IN_PROGRESS field
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Return {self.order.id} - {self.product.sku}"


class CustomerReturnModels(models.Model):

    CONDITION_CHOICES = [
        ("SAFE", "Safe"),
        ("DAMAGED", "Damaged"),
        ("LOST", "Lost"),
    ]

    RETURN_STATUS = [
        ("IN_PROGRESS", "In Progress"),
        ("APPROVED", "Approved"),
        ("NOT_APPROVED", "Not Approved"),
    ]

    RETURN_REASON = [
        ("AGENT_ERROR", "Agent Error"),
        ("LACK_OF_STOCK", "Lack of Stock"),
        ("CUSTOMER_ERROR", "Customer Error"),
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="customer_returns")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()

    condition = models.CharField(
        max_length=10,
        choices=CONDITION_CHOICES
    )

    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refund_status = models.CharField(
        max_length=10,
        choices=[
            ("PENDING", "Pending"),
            ("REFUNDED", "Refunded"),
            ("REJECTED", "Rejected"),
        ],
        default="PENDING"
    )

    reason = models.TextField(blank=True, null=True)
    received_at = models.DateTimeField(auto_now_add=True)

    return_status = models.CharField(
        max_length=20,
        choices=RETURN_STATUS,
        default="IN_PROGRESS"
    )

    return_charges = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    return_receive_date = models.DateField(blank=True, null=True)
    return_photo = models.ImageField(upload_to="customer_returns/photos/", blank=True, null=True)
    return_video = models.FileField(upload_to="customer_returns/videos/", blank=True, null=True)
    return_reason = models.CharField(max_length=20, choices=RETURN_REASON, blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)

class OrderBarcode(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="barcodes")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    barcode = models.CharField(max_length=200, unique=True)
    serial = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("order", "barcode")

    def __str__(self):
        return f"Order {self.order.id} - {self.barcode}"

# class OrderPayment(models.Model):
#     order = models.ForeignKey("Order", on_delete=models.CASCADE, related_name="payments")
#     amount = models.DecimalField(max_digits=10, decimal_places=2)
#     payment_method = models.CharField(max_length=50, null=True, blank=True)
#     transaction_id = models.CharField(max_length=255, null=True, blank=True)
#     payment_date = models.DateTimeField(auto_now_add=True)

#     def __str__(self):
#         return f"{self.order.id} - {self.amount}"

class CourirPartnerModel(models.Model):
    title = models.CharField(max_length=200)

    def __str__(self):
        return self.title


class MediatorModels(models.Model):
    title = models.CharField(max_length=200)
    courier_partner = models.ForeignKey(
        CourirPartnerModel,
        on_delete=models.CASCADE,
        related_name="mediators"
    )

    def __str__(self):
        return self.title
        
class Shipment(models.Model):
    order = models.ForeignKey(
        "Order",
        on_delete=models.CASCADE,
        related_name="shipments"
    )

    courier_partner = models.ForeignKey(
        "CourirPartnerModel",
        on_delete=models.CASCADE,
        related_name="shipments"
    )

    mediator = models.ForeignKey(
        "MediatorModels",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shipments"
    )

    tracking_id = models.CharField(max_length=100, unique=True)

    shipping_date = models.DateField()

    tracking_url = models.URLField(blank=True, null=True)

    shipping_expense = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    other_expense = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.order.id} - {self.tracking_id}"
        
class OrderStatus(models.Model):
    order_id = models.IntegerField()
    status = models.IntegerField()
    json = models.JSONField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class UserActivityLog(models.Model):
    """An immutable audit event sent by an authenticated app user."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    event = models.CharField(max_length=100, db_index=True)
    screen = models.CharField(max_length=100, blank=True, db_index=True)
    target = models.CharField(max_length=150, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    client_timestamp = models.DateTimeField(null=True, blank=True)
    app_version = models.CharField(max_length=40, blank=True)
    device_id = models.CharField(max_length=128, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "-created_at"), name="activity_user_created_idx"),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.event}"


class QuotationSettings(models.Model):
    company_name = models.CharField(max_length=180, blank=True)
    address = models.TextField(blank=True)
    gstin = models.CharField(max_length=30, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    account_name = models.CharField(max_length=120, blank=True)
    account_number = models.CharField(max_length=60, blank=True)
    ifsc = models.CharField(max_length=30, blank=True)
    branch = models.CharField(max_length=120, blank=True)
    terms = models.TextField(blank=True, default="Quotation valid for 15 days.")
    updated_at = models.DateTimeField(auto_now=True)


class Quotation(models.Model):
    number = models.CharField(max_length=40, unique=True)
    customer_name = models.CharField(max_length=180)
    customer_phone = models.CharField(max_length=30, blank=True)
    customer_email = models.EmailField(blank=True)
    customer_address = models.TextField(blank=True)
    customer_gstin = models.CharField(max_length=30, blank=True)
    customer_state = models.CharField(max_length=80, blank=True)
    customer_state_code = models.CharField(max_length=10, blank=True)
    consignee_name = models.CharField(max_length=180, blank=True)
    consignee_address = models.TextField(blank=True)
    consignee_gstin = models.CharField(max_length=30, blank=True)
    consignee_state = models.CharField(max_length=80, blank=True)
    consignee_state_code = models.CharField(max_length=10, blank=True)
    payment_terms = models.CharField(max_length=180, blank=True)
    buyer_reference = models.CharField(max_length=180, blank=True)
    other_references = models.CharField(max_length=180, blank=True)
    dispatched_through = models.CharField(max_length=180, blank=True)
    destination = models.CharField(max_length=180, blank=True)
    delivery_terms = models.TextField(blank=True)
    quote_date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    shipment_details = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    shipping_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class QuotationItem(models.Model):
    quotation = models.ForeignKey(Quotation, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL)
    product_name = models.CharField(max_length=180)
    sku = models.CharField(max_length=80, blank=True)
    hsn_code = models.CharField(max_length=30, blank=True)
    due_on = models.DateField(null=True, blank=True)
    unit = models.CharField(max_length=20, default="PCS")
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    gst_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    taxable_amount = models.DecimalField(max_digits=14, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
