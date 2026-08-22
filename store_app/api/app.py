from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils.timezone import now
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

from store_app.access_control import ACTIONS, MODULES, default_action_permissions, get_access_profile
from store_app.models import (
    Inventory,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    PurchaseBill,
    PurchaseBillItem,
    SalesChannel,
    StockMovement,
    UserAccessProfile,
    Vendor,
)
from store_app.serializers import OrderDetailSerializer, OrderListSerializer, PurchaseBillSerializer, VendorSerializer


LOW_STOCK_THRESHOLD = 10
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _profile_payload(user):
    profile = get_access_profile(user)
    action_permissions = (
        default_action_permissions()
        if profile.role == UserAccessProfile.ROLE_SUPER_ADMIN or user.is_superuser
        else profile.action_permissions or {}
    )
    modules = (
        [module["key"] for module in MODULES]
        if profile.role == UserAccessProfile.ROLE_SUPER_ADMIN or user.is_superuser
        else profile.modules or []
    )
    return {
        "id": user.id,
        "username": user.username,
        "name": user.get_full_name() or user.username,
        "email": user.email,
        "role": profile.role,
        "role_display": profile.get_role_display(),
        "modules": modules,
        "action_permissions": action_permissions,
        "module_catalog": MODULES,
        "actions": ACTIONS,
    }


def _app_has_module(user, *module_keys):
    if not getattr(user, "is_authenticated", False):
        return False
    if not isinstance(getattr(user, "id", None), int):
        return False
    profile = get_access_profile(user)
    if user.is_superuser or profile.role == UserAccessProfile.ROLE_SUPER_ADMIN:
        return True
    return any(profile.has_module(module_key) for module_key in module_keys)


def _app_forbidden():
    return Response(
        {"detail": "You do not have access to this module."},
        status=status.HTTP_403_FORBIDDEN,
    )


class AppLoginAPIView(APIView):
    permission_classes = []

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        if not username or not password:
            return Response(
                {"message": "Username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"message": "Invalid username or password."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not user.is_active:
            return Response(
                {"message": "This user is inactive."},
                status=status.HTTP_403_FORBIDDEN,
            )

        token = AccessToken.for_user(user)
        token.set_exp(lifetime=timedelta(days=7))
        profile = _profile_payload(user)
        token["role"] = profile["role"]
        token["modules"] = profile["modules"]

        return Response({
            "token": str(token),
            "user": profile,
        })


def _date_range(request):
    start = request.query_params.get("start")
    end = request.query_params.get("end")

    if start and end:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
        return start_date, end_date

    today = now()
    return today.replace(day=1), today


def _money(value):
    if value is None:
        value = Decimal("0.00")
    return float(value)


def _limit(request):
    try:
        limit = int(request.query_params.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def _image_url(request, image):
    if not image:
        return None
    try:
        return request.build_absolute_uri(image.url)
    except Exception:
        return None


def _latest_status_map(order_ids):
    statuses = (
        OrderStatus.objects
        .filter(order_id__in=order_ids)
        .order_by("order_id", "-created_at")
    )
    latest = {}
    for status in statuses:
        latest.setdefault(status.order_id, status)
    return latest


class AppDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _app_has_module(request.user, "dashboard", "main_info"):
            return _app_forbidden()
        start_date, end_date = _date_range(request)

        inventory_value = (
            Inventory.objects
            .select_related("product")
            .annotate(
                line_value=ExpressionWrapper(
                    F("quantity") * F("product__unit_purchase_price"),
                    output_field=DecimalField(max_digits=18, decimal_places=2),
                )
            )
            .aggregate(total=Sum("line_value"))
            .get("total")
        ) or Decimal("0.00")

        total_sales = (
            OrderItem.objects
            .filter(order__created_at__range=(start_date, end_date))
            .aggregate(total=Sum(F("quantity") * F("unit_price")))
            .get("total")
        ) or Decimal("0.00")

        total_purchase = (
            PurchaseBillItem.objects
            .filter(bill__created_at__range=(start_date, end_date))
            .aggregate(total=Sum(F("quantity") * F("unit_price")))
            .get("total")
        ) or Decimal("0.00")

        total_stock = Inventory.objects.aggregate(total=Sum("quantity")).get("total") or 0
        products = (
            Inventory.objects
            .select_related("product")
            .order_by("product__name")
        )
        stock_products = [
            {
                "product_id": row.product_id,
                "name": row.product.name,
                "sku": row.product.sku,
                "quantity": row.quantity,
                "image": _image_url(request, row.product.product_image),
            }
            for row in products[:50]
        ]

        top_products = list(
            OrderItem.objects
            .filter(order__created_at__range=(start_date, end_date))
            .values("product_id", "product__name", "product__sku")
            .annotate(total_sold=Sum("quantity"))
            .order_by("-total_sold")[:5]
        )

        recent_orders = list(
            Order.objects
            .filter(is_deleted=False)
            .select_related("channel")
            .order_by("-created_at")[:10]
        )
        status_map = _latest_status_map([order.id for order in recent_orders])
        for order in recent_orders:
            status = status_map.get(order.id)
            order._prefetched_statuses = [status] if status else []

        recent_movements = [
            {
                "id": movement.id,
                "product_id": movement.product_id,
                "product_name": movement.product.name if movement.product else "",
                "sku": movement.product.sku if movement.product else "",
                "delta": movement.delta,
                "reason": movement.reason,
                "condition": movement.condition,
                "note": movement.note,
                "created_at": movement.created_at,
            }
            for movement in (
                StockMovement.objects
                .select_related("product")
                .order_by("-created_at")[:10]
            )
        ]

        channels = [
            {"id": channel.id, "name": channel.name}
            for channel in SalesChannel.objects.order_by("name")
        ]

        return Response({
            "date_range": {
                "start": start_date.date().isoformat(),
                "end": (end_date - timedelta(days=1)).date().isoformat(),
            },
            "summary": {
                "total_stock": total_stock,
                "low_stock_count": Inventory.objects.filter(quantity__lte=LOW_STOCK_THRESHOLD).count(),
                "inventory_value": _money(inventory_value),
                "total_sales": _money(total_sales),
                "total_purchase": _money(total_purchase),
                "orders_count": Order.objects.filter(created_at__range=(start_date, end_date), is_deleted=False).count(),
                "products_count": Product.objects.count(),
                "vendors_count": Vendor.objects.count(),
                "users_count": User.objects.count(),
                "purchase_bills_count": PurchaseBill.objects.filter(is_deleted=False).count(),
            },
            "charts": {
                "top_products": top_products,
                "purchase_vs_sale": {
                    "purchase": _money(total_purchase),
                    "sale": _money(total_sales),
                },
            },
            "recent_orders": OrderListSerializer(recent_orders, many=True).data,
            "recent_movements": recent_movements,
            "products": stock_products,
            "low_stock": [item for item in stock_products if item["quantity"] <= LOW_STOCK_THRESHOLD],
            "channels": channels,
        })


class AppProductsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _app_has_module(request.user, "items"):
            return _app_forbidden()
        search = request.query_params.get("search", "").strip()
        low_stock = request.query_params.get("low_stock") in {"1", "true", "True"}
        limit = _limit(request)

        rows = Inventory.objects.select_related("product", "product__vendor").order_by("-product_id")
        if search:
            rows = rows.filter(
                Q(product__name__icontains=search)
                | Q(product__sku__icontains=search)
                | Q(product__vendor__name__icontains=search)
            )
        if low_stock:
            rows = rows.filter(quantity__lte=LOW_STOCK_THRESHOLD)

        data = [
            {
                "id": row.product_id,
                "name": row.product.name,
                "sku": row.product.sku,
                "vendor": {
                    "id": row.product.vendor_id,
                    "name": row.product.vendor.name if row.product.vendor else "",
                },
                "quantity": row.quantity,
                "purchase_price": _money(row.product.unit_purchase_price),
                "wholesale_price": _money(row.product.wholesale_price),
                "retailer_price": _money(row.product.retailer_price),
                "image": _image_url(request, row.product.product_image),
                "size": row.product.size,
                "color": row.product.color,
                "material": row.product.material,
            }
            for row in rows[:limit]
        ]

        return Response({"data": data, "count": len(data)})


class AppProductSKUUpdateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not _app_has_module(request.user, "items"):
            return _app_forbidden()

        product = Product.objects.filter(pk=pk).first()
        if not product:
            return Response({"detail": "Product not found."}, status=status.HTTP_404_NOT_FOUND)

        sku = str(request.data.get("sku", "")).strip()
        if not sku:
            return Response({"detail": "sku is required."}, status=status.HTTP_400_BAD_REQUEST)
        if len(sku) > 150:
            return Response({"detail": "sku cannot exceed 150 characters."}, status=status.HTTP_400_BAD_REQUEST)
        if Product.objects.exclude(pk=product.pk).filter(sku=sku).exists():
            return Response({"detail": "This SKU is already used by another product."}, status=status.HTTP_409_CONFLICT)

        old_sku = product.sku
        product.sku = sku
        product.save(update_fields=["sku"])
        return Response({
            "id": product.id,
            "name": product.name,
            "old_sku": old_sku,
            "sku": product.sku,
            "detail": "Product SKU updated successfully.",
        })


class AppVendorsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _app_has_module(request.user, "vendors"):
            return _app_forbidden()
        search = request.query_params.get("search", "").strip()
        limit = _limit(request)
        vendors = Vendor.objects.order_by("-id")
        if search:
            vendors = vendors.filter(
                Q(name__icontains=search)
                | Q(firm_name__icontains=search)
                | Q(mobile__icontains=search)
                | Q(email__icontains=search)
                | Q(city__icontains=search)
                | Q(state__icontains=search)
                | Q(gst_number__icontains=search)
            )
        vendors = vendors[:limit]
        return Response({"data": VendorSerializer(vendors, many=True).data, "count": len(vendors)})


class AppUsersAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _app_has_module(request.user, "users"):
            return _app_forbidden()
        search = request.query_params.get("search", "").strip()
        limit = _limit(request)
        users = User.objects.select_related("access_profile").order_by("-date_joined")
        if search:
            users = users.filter(
                Q(username__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
            )
        users = list(users[:limit])
        role_labels = dict(UserAccessProfile.ROLE_CHOICES)
        data = []
        for user in users:
            profile = getattr(user, "access_profile", None)
            role = profile.role if profile else UserAccessProfile.ROLE_USER
            data.append({
                "id": user.id,
                "username": user.username,
                "name": user.get_full_name() or user.username,
                "email": user.email,
                "role": role,
                "role_display": role_labels.get(role, role),
                "is_active": user.is_active,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
                "date_joined": user.date_joined,
                "modules": profile.modules if profile else [],
            })
        return Response({"data": data, "count": len(data)})


class AppPurchasesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _app_has_module(request.user, "purchase"):
            return _app_forbidden()
        search = request.query_params.get("search", "").strip()
        limit = _limit(request)
        bills = (
            PurchaseBill.objects
            .filter(is_deleted=False)
            .select_related("vendor")
            .prefetch_related("items__product")
            .order_by("-created_at")
        )
        if search:
            bills = bills.filter(
                Q(bill_number__icontains=search)
                | Q(vendor__name__icontains=search)
                | Q(status__icontains=search)
            )
        bills = bills[:limit]
        return Response({"data": PurchaseBillSerializer(bills, many=True).data, "count": len(bills)})


class AppOrdersAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _app_has_module(request.user, "orders"):
            return _app_forbidden()
        status_filter = request.query_params.get("status", "ALL").upper()
        search = request.query_params.get("search", "").strip()
        limit = _limit(request)

        orders = (
            Order.objects
            .filter(is_deleted=False)
            .select_related("channel")
            .prefetch_related("items__product", "remarks_list", "shipments")
            .order_by("-id")
        )

        if search:
            query = Q(customer_name__icontains=search) | Q(channel_order_id__icontains=search)
            if search.isdigit():
                query |= Q(id=int(search))
            orders = orders.filter(query)

        orders = list(orders.distinct()[:MAX_LIMIT])
        status_map = _latest_status_map([order.id for order in orders])
        for order in orders:
            status = status_map.get(order.id)
            order._prefetched_statuses = [status] if status else []

        status_codes = {
            "IN_PROCESS": 1,
            "PACKED": 2,
            "IN_TRANSIT": 3,
            "DELIVERED": 4,
            "CANCELLED": 5,
            "COURIER_RETURN": 6,
            "CUSTOMER_RETURN": 7,
            "RETURNED": 8,
        }
        if status_filter != "ALL":
            status_code = status_codes.get(status_filter)
            if status_code:
                orders = [
                    order for order in orders
                    if (status_map.get(order.id).status if status_map.get(order.id) else order.order_status) == status_code
                ]

        orders = orders[:limit]
        return Response({"data": OrderListSerializer(orders, many=True).data, "count": len(orders)})


class AppOrderDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        if not _app_has_module(request.user, "orders"):
            return _app_forbidden()
        try:
            order = (
                Order.objects
                .prefetch_related("items__product", "shipments")
                .get(id=order_id, is_deleted=False)
            )
        except Order.DoesNotExist:
            return Response({"message": "Order not found"}, status=404)

        data = OrderDetailSerializer(order).data
        status_map = _latest_status_map([order.id])
        latest_status = status_map.get(order.id)
        status_code = latest_status.status if latest_status else order.order_status
        data["order_status"] = status_code
        data["latest_status"] = {
            "status": status_code,
            "note": (latest_status.json or {}).get("message") or (latest_status.json or {}).get("note") or "",
            "created_at": latest_status.created_at if latest_status else None,
        }
        data["status_history"] = [
            {
                "id": item.id,
                "status": item.status,
                "json": item.json,
                "created_at": item.created_at,
            }
            for item in OrderStatus.objects.filter(order_id=order.id).order_by("-created_at")
        ]
        return Response(data)
