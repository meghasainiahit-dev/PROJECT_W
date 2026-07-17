import os

import qrcode
from django.conf import settings
from django.shortcuts import render, redirect
from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from django.utils.text import slugify
from django.utils.timezone import now
from datetime import datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Vendor, Product, PurchaseBill, PurchaseBillItem
from django.db.models import Sum
from decimal import Decimal
from django.db.models import Q
from django.core.paginator import Paginator


from .models import (
    Inventory,
    SalesChannel,
    StockMovement,
    Product,
    OrderItem,
    PurchaseBillItem,
    Order
)

LOW_STOCK_THRESHOLD = 5


def media_url(path):
    if not path:
        return ""
    path = str(path)
    if path.startswith(("http://", "https://")):
        return path
    return f"{settings.MEDIA_URL.rstrip('/')}/{path.lstrip('/')}"


# =========================
# HOME PAGE
# =========================
def home(request):
    total_stock = Inventory.objects.aggregate(
        total=Sum('quantity')
    )['total'] or 0

    low_stock_count = Inventory.objects.filter(
        quantity__lte=LOW_STOCK_THRESHOLD
    ).count()

    total_value = Inventory.objects.annotate(
        line_value=ExpressionWrapper(
            F('quantity') * F('product__unit_purchase_price'),
            output_field=DecimalField()
        )
    ).aggregate(total=Sum('line_value'))['total'] or 0

    recent_movements = (
        StockMovement.objects
        .select_related('product', 'product__inventory', 'channel')
        .order_by('-created_at')[:10]
    )

    channels = SalesChannel.objects.all()

    context = {
        'total_stock': total_stock,
        'low_stock_count': low_stock_count,
        'total_value': total_value,
        'recent_movements': recent_movements,
        'channels': channels,
    }

    return render(request, 'index.html', context)


# =========================
# STATIC PAGES
# =========================
def about(request):
    return render(request, 'pages/about.html')


def contact(request):
    return render(request, 'pages/contact.html')


# =========================
# ITEMS PAGE (SAME ROUTE DATA)
# =========================
def items_page(request):

    # 🔐 Optional auth
    # if not request.session.get("is_admin"):
    #     return redirect("/login/")

    # 📅 Date filter (future ready)
    start = request.GET.get("start")
    end = request.GET.get("end")

    if start and end:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
    else:
        today = now()
        start_date = today.replace(day=1)
        end_date = today

    per_page = request.GET.get("per_page", "25")
    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        per_page = 25
    per_page = min(max(per_page, 10), 100)

    # 📦 PRODUCTS (UPDATED)
    products_qs = (
        Inventory.objects
        .select_related("product")
        .values(
            "product__id",          # 🔥 needed for edit/delete
            "product__name",
            "product__sku",
            "product__product_image",      # 🔥 image support
            "quantity"
        )
       .order_by("-product__id")
    )

    paginator = Paginator(products_qs, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))
    products = list(page_obj.object_list)

    for product in products:
        product["product_image_url"] = media_url(product.get("product__product_image"))

    # 📊 Extra stats (optional but useful)
    total_products = paginator.count

    context = {
        "products": products,
        "total_products": total_products,
        "page_obj": page_obj,
        "paginator": paginator,
        "per_page": per_page,
    }

    return render(request, "inventory/items.html", context)


def item_details_page(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("vendor", "hsn", "inventory"),
        pk=pk,
    )
    inventory = getattr(product, "inventory", None)
    stock_qty = inventory.quantity if inventory else 0

    qr_dir = os.path.join(settings.MEDIA_ROOT, "qrcodes")
    os.makedirs(qr_dir, exist_ok=True)
    qr_filename = f"product-{product.id}-{slugify(product.sku)[:80]}.png"
    qr_path = os.path.join(qr_dir, qr_filename)
    if not os.path.exists(qr_path):
        qrcode.make(product.sku).save(qr_path)

    dimension_parts = [product.length, product.width, product.height]
    dimensions = " x ".join([str(part) for part in dimension_parts if part])
    if dimensions and product.unit:
        dimensions = f"{dimensions} {product.unit}"

    return render(request, "inventory/item-details.html", {
        "product": product,
        "stock_qty": stock_qty,
        "qr_url": f"{settings.MEDIA_URL}qrcodes/{qr_filename}",
        "dimensions": dimensions,
    })

def inventory_page(request):
    return render(request, "inventory/inventory.html")

def purchase_page(request):
    return render(request, "inventory/purchase.html")

def create_purchase_page(request):
    return render(request, "inventory/create-purchase.html")

def purchase_details_page(request):
    return render(request, "inventory/purchase-details.html")

def add_item_page(request, pk=None):
    return render(request, "inventory/add-item.html", {"product_id": pk})


def vendors_page(request):
    search = request.GET.get("search", "").strip()

    vendors = Vendor.objects.all().order_by("-id")

    if search:
        vendors = vendors.filter(
            Q(name__icontains=search) |
            Q(firm_name__icontains=search) |
            Q(mobile__icontains=search) |
            Q(email__icontains=search) |
            Q(city__icontains=search) |
            Q(state__icontains=search) |
            Q(gst_number__icontains=search)
        )

    return render(request, "inventory/vendors.html", {
        "vendors": vendors,
        "total_vendors": vendors.count(),
        "search": search,
    })



def add_vendor_page(request):
    if request.method == "POST":
        Vendor.objects.create(
            name=request.POST.get("name", "").strip(),
            country_code=request.POST.get("country_code", "+91"),
            mobile=request.POST.get("mobile", "").strip(),
            email=request.POST.get("email", "").strip() or None,
            address=request.POST.get("address", "").strip(),
            country=request.POST.get("country", "").strip(),
            state=request.POST.get("state", "").strip(),
            city=request.POST.get("city", "").strip(),
            pin_code=request.POST.get("pin_code", "").strip(),
            with_Gst=request.POST.get("with_Gst") == "true",
            firm_name=request.POST.get("firm_name", "").strip() or None,
            gst_number=request.POST.get("gst_number", "").strip() or None,
        )
        return redirect("/api/vendors-page/")

    return render(request, "inventory/add-vendor.html")


def vendor_details_page(request, vendor_id):
    vendor = get_object_or_404(Vendor, id=vendor_id)
    vendors = Vendor.objects.all().order_by("name")

    total_bills = PurchaseBill.objects.filter(vendor=vendor).count()
    total_purchase = PurchaseBillItem.objects.filter(
        bill__vendor=vendor
    ).aggregate(total=Sum("quantity"))["total"] or 0

    total_business = PurchaseBill.objects.filter(
        vendor=vendor
    ).aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")

    products = Product.objects.filter(vendor=vendor).order_by("name")

    return render(request, "inventory/vendor-details.html", {
        "vendor": vendor,
        "vendors": vendors,
        "total_vendors": vendors.count(),
        "total_bills": total_bills,
        "total_purchase": total_purchase,
        "total_business": total_business,
        "products": products,
    })


def edit_vendor_page(request, vendor_id):
    vendor = get_object_or_404(Vendor, id=vendor_id)

    if request.method == "POST":
        vendor.name = request.POST.get("name", "").strip()
        vendor.country_code = request.POST.get("country_code", "+91")
        vendor.mobile = request.POST.get("mobile", "").strip()
        vendor.email = request.POST.get("email", "").strip() or None
        vendor.address = request.POST.get("address", "").strip()
        vendor.country = request.POST.get("country", "").strip()
        vendor.state = request.POST.get("state", "").strip()
        vendor.city = request.POST.get("city", "").strip()
        vendor.pin_code = request.POST.get("pin_code", "").strip()
        vendor.with_Gst = request.POST.get("with_Gst") == "true"
        vendor.firm_name = request.POST.get("firm_name", "").strip() or None
        vendor.gst_number = request.POST.get("gst_number", "").strip() or None
        vendor.save()

        return redirect(f"/api/vendors-page/{vendor.id}/page/")

    return render(request, "inventory/edit-vendor.html", {"vendor": vendor})


def delete_vendor(request, vendor_id):
    vendor = get_object_or_404(Vendor, id=vendor_id)

    if request.method == "POST":
        vendor.delete()
        return redirect("/api/vendors-page/")

    return redirect(f"/api/vendors-page/{vendor.id}/page/")


def orders_page(request):
    return render(request, "inventory/orders.html")


def couriers_page(request):
    return render(request, "inventory/couriers.html")


def order_details_page(request):
    return render(request, "inventory/order-details.html")


def create_order_page(request):
    channels = list(
        SalesChannel.objects.order_by("name").values("id", "name")
    )
    products = []

    for product in Product.objects.select_related("inventory").order_by("name"):
        inventory = getattr(product, "inventory", None)
        products.append({
            "id": product.id,
            "name": product.name,
            "sku": product.sku,
            "size": product.size or "",
            "color": product.color or "",
            "material": product.material or "",
            "price": float(product.retailer_price or product.unit_purchase_price or 0),
            "wholesale_price": float(product.wholesale_price or 0),
            "retailer_price": float(product.retailer_price or 0),
            "quantity": inventory.quantity if inventory else 0,
        })

    return render(request, "inventory/create-order.html", {
        "channels": channels,
        "products": products,
    })
