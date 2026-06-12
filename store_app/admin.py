from django.contrib import admin
from .models import *


@admin.register(UserAccessProfile)
class UserAccessProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "updated_at")
    search_fields = ("user__username", "user__email", "user__first_name")
    list_filter = ("role",)
from .models import ProductUnit

@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'state', 'country_code','mobile')
    search_fields = ('name', 'city')


@admin.register(SalesChannel)
class SalesChannelAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'vendor', 'sku', 'size', 'color', 'material', 'serial')
    list_filter = ('vendor', 'color', 'size', 'material')
    search_fields = ('name', 'sku', 'barcode')


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'quantity')
    search_fields = ('product__sku',)
 

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'channel', 'customer_name', 'created_at')
    list_filter = ('channel', 'created_at')
    


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'quantity', 'unit_price')


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('product', 'delta', 'reason', 'created_at')
    list_filter = ('reason', 'channel')

@admin.register(GSTTable)
class GSTViewAdmin(admin.ModelAdmin):
    list_display = ('id', 'gst_percentage', 'created_at')
@admin.register(HsnTable)
class HsnViewAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'gst_percentage')

@admin.register(CourierReturn)
class CourierReturnAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "product",
        "quantity",
        "condition",
        "claim_status",
        "claim_result",
        "claim_amount",
        "received_at"
    )

    list_filter = (
        "condition",
        "claim_status",
        "claim_result"
    )

    search_fields = (
        "order__id",
        "product__sku"
    )

    
@admin.register(ProductUnit)
class ProductUnitAdmin(admin.ModelAdmin):
    list_display  = ("serial_number", "product", "status", "order", "created_at")
    list_filter   = ("status",)
    search_fields = ("serial_number", "product__sku")
    raw_id_fields = ("product", "order")
class MediatorInline(admin.TabularInline):  # ya StackedInline
    model = MediatorModels
    extra = 1  # default kitne blank form dikhenge


@admin.register(CourirPartnerModel)
class CourirPartnerAdmin(admin.ModelAdmin):
    list_display = ("id", "title")
    search_fields = ("title",)
    inlines = [MediatorInline]


@admin.register(MediatorModels)
class MediatorAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "courier_partner")
    search_fields = ("title",)
    list_filter = ("courier_partner",)
