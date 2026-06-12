import json
from django.shortcuts import redirect, render
from django.http import JsonResponse
from django.db.models import Sum, F
from django.utils.timezone import now
from datetime import datetime, timedelta
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.views.csrf import csrf_failure as default_csrf_failure
from store_app.access_control import (
    ACTIONS,
    MODULES,
    modules_from_action_permissions,
    normalize_action_permissions,
    get_access_profile,
    user_can_access,
    user_can_action,
    first_allowed_url,
)
from store_app.models import UserAccessProfile
from ..models import (
    Order, OrderItem, Product, Inventory, PurchaseBillItem
)
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie


def csrf_failure(request, reason=""):
    if request.path == "/login/" and request.user.is_authenticated:
        return redirect(first_allowed_url(request.user))
    return default_csrf_failure(request, reason=reason)


@csrf_exempt
def login_api(request):
    if request.method == "POST":
        data = json.loads(request.body or "{}")
        username = data.get("username")
        password = data.get("password")

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return JsonResponse({"success": True})

        return JsonResponse({"success": False})

    return JsonResponse({"success": False, "error": "POST required"}, status=405)


@ensure_csrf_cookie
def login_page(request):
    if request.user.is_authenticated:
        return redirect("/dashboard/")

    if request.method == "POST":
        action = request.POST.get("action")
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect(first_allowed_url(user))
        messages.error(request, "Invalid username or password.")

    return render(request, "login.html")


def dashboard(request):
    if not request.user.is_authenticated:
        return redirect("/login/")

    profile = get_access_profile(request.user)
    return render(request, "inventory/dashboard.html", {"access_profile": profile})


def users_page(request):
    if not request.user.is_authenticated:
        return redirect("/login/")

    if not user_can_access(request.user, "users"):
        messages.error(request, "You do not have access to user management.")
        return redirect("/dashboard/")

    current_profile = get_access_profile(request.user)
    current_can_manage_super_admin = (
        request.user.is_superuser
        or current_profile.role == UserAccessProfile.ROLE_SUPER_ADMIN
    )

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_user":
            full_name = (request.POST.get("full_name") or "").strip()
            email = (request.POST.get("email") or "").strip()
            username = (request.POST.get("username") or "").strip()
            password = request.POST.get("password") or ""
            confirm_password = request.POST.get("confirm_password") or ""
            role = request.POST.get("role") or UserAccessProfile.ROLE_USER
            action_permissions = normalize_action_permissions(role, request.POST)
            modules = modules_from_action_permissions(action_permissions)

            if not user_can_action(request.user, "users", "add"):
                messages.error(request, "You do not have permission to add users.")
            elif role not in dict(UserAccessProfile.ROLE_CHOICES):
                messages.error(request, "Invalid role selected.")
            elif role == UserAccessProfile.ROLE_SUPER_ADMIN and not current_can_manage_super_admin:
                messages.error(request, "Only Super Admin can create another Super Admin.")
            elif not username or not password:
                messages.error(request, "Username and password are required.")
            elif password != confirm_password:
                messages.error(request, "Passwords do not match.")
            elif User.objects.filter(username=username).exists():
                messages.error(request, "This username already exists.")
            else:
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=full_name,
                    is_staff=role in [UserAccessProfile.ROLE_SUPER_ADMIN, UserAccessProfile.ROLE_ADMIN],
                )
                UserAccessProfile.objects.update_or_create(
                    user=user,
                    defaults={
                        "role": role,
                        "modules": modules,
                        "action_permissions": action_permissions,
                    },
                )
                messages.success(request, f"User '{username}' created successfully.")

            return redirect("/users/")

        if action == "update_access":
            user_id = request.POST.get("user_id")
            target = User.objects.filter(id=user_id).first()
            if not target:
                messages.error(request, "User not found.")
            elif not user_can_action(request.user, "users", "edit"):
                messages.error(request, "You do not have permission to edit user access.")
            elif target == request.user:
                messages.error(request, "You cannot edit your own access.")
            else:
                role = request.POST.get("role") or UserAccessProfile.ROLE_USER
                action_permissions = normalize_action_permissions(role, request.POST)
                modules = modules_from_action_permissions(action_permissions)
                target_profile = get_access_profile(target)
                if role not in dict(UserAccessProfile.ROLE_CHOICES):
                    messages.error(request, "Invalid role selected.")
                elif (
                    (role == UserAccessProfile.ROLE_SUPER_ADMIN or target_profile.role == UserAccessProfile.ROLE_SUPER_ADMIN)
                    and not current_can_manage_super_admin
                ):
                    messages.error(request, "Only Super Admin can manage Super Admin access.")
                else:
                    profile, _ = UserAccessProfile.objects.update_or_create(
                        user=target,
                        defaults={
                            "role": role,
                            "modules": modules,
                            "action_permissions": action_permissions,
                        },
                    )
                    target.is_staff = role in [UserAccessProfile.ROLE_SUPER_ADMIN, UserAccessProfile.ROLE_ADMIN]
                    target.is_superuser = role == UserAccessProfile.ROLE_SUPER_ADMIN
                    target.save(update_fields=["is_staff", "is_superuser"])
                    messages.success(request, f"Access updated for {target.username}.")

            return redirect("/users/")

        if action == "toggle_active":
            user_id = request.POST.get("user_id")
            target = User.objects.filter(id=user_id).first()
            if not target:
                messages.error(request, "User not found.")
            elif not user_can_action(request.user, "users", "edit"):
                messages.error(request, "You do not have permission to update users.")
            elif target == request.user:
                messages.error(request, "You cannot deactivate your own account.")
            else:
                target.is_active = not target.is_active
                target.save(update_fields=["is_active"])
                messages.success(request, f"{target.username} is now {'active' if target.is_active else 'inactive'}.")

            return redirect("/users/")

    users = list(User.objects.select_related("access_profile").all().order_by("-date_joined"))
    for user in users:
        profile = get_access_profile(user)
        user.access_rows = [
            {
                "module": module,
                "actions": (profile.action_permissions or {}).get(module["key"], []),
            }
            for module in MODULES
        ]

    return render(request, "inventory/users.html", {
        "users": users,
        "modules": MODULES,
        "actions": ACTIONS,
        "roles": UserAccessProfile.ROLE_CHOICES,
    })


def logout_page(request):
    logout(request)
    return redirect("/login/")


def billing_coming_soon(request):
    return render(request, "billing-coming-soon.html", status=404)


def dashboard_data(request):
    # Date filter
    start = request.GET.get("start")
    end = request.GET.get("end")

    if start and end:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
    else:
        today = now()
        start_date = today.replace(day=1)
        end_date = today

    # -------------------------
    # TOP SELLING PRODUCTS
    # -------------------------
    top_products = (
        OrderItem.objects
        .filter(order__created_at__range=(start_date, end_date))
        .values("product__name")
        .annotate(total_sold=Sum("quantity"))
        .order_by("-total_sold")[:5]
    )

    # -------------------------
    # TOTAL SALES AMOUNT
    # -------------------------
    total_sales = (
        OrderItem.objects
        .filter(order__created_at__range=(start_date, end_date))
        .aggregate(
            total=Sum(F("quantity") * F("unit_price"))
        )["total"] or 0
    )

    # -------------------------
    # TOTAL PURCHASE AMOUNT
    # -------------------------
    total_purchase = (
        PurchaseBillItem.objects
        .filter(bill__created_at__range=(start_date, end_date))
        .aggregate(
            total=Sum(F("quantity") * F("unit_price"))
        )["total"] or 0
    )

    # -------------------------
    # ORDERS LIST
    # -------------------------
    orders = list(
        Order.objects
        .filter(created_at__range=(start_date, end_date))
        .values("id", "customer_name", "paid_status", "created_at")
        .order_by("-created_at")[:10]
    )

    # -------------------------
    # PRODUCT + STOCK
    # -------------------------
    products = list(
        Inventory.objects
        .select_related("product")
        .values(
            "product__name",
            "product__sku",
            "quantity"
        )
    )

    low_stock = [p for p in products if p["quantity"] <= 10]

    return JsonResponse({
        "top_products": list(top_products),
        "total_sales": float(total_sales),
        "total_purchase": float(total_purchase),
        "orders": orders,
        "products": products,
        "low_stock": low_stock
    })
def items_page(request):
    if not request.session.get("is_admin"):
        return redirect("/login/")

    from django.db.models import Sum, F
    from django.utils.timezone import now
    from datetime import datetime, timedelta
    from ..models import OrderItem, Inventory, PurchaseBillItem, Order

    # Date filter
    start = request.GET.get("start")
    end = request.GET.get("end")

    if start and end:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
    else:
        today = now()
        start_date = today.replace(day=1)
        end_date = today

    # PRODUCTS
    products = list(
        Inventory.objects
        .select_related("product")
        .values(
            "product__name",
            "product__sku",
            "quantity"
        )
    )

    low_stock = [p for p in products if p["quantity"] <= 10]

    return render(request, "inventory/items.html", {
        "products": products,
        "low_stock": low_stock
    })
