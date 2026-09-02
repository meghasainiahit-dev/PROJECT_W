import json

from django.contrib import messages
from django.contrib.auth.models import AnonymousUser, User
from django.db.utils import OperationalError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from .models import UserAccessProfile


MODULES = [
    {"key": "dashboard", "label": "Dashboard", "icon": "bi-speedometer2", "url": "/api/home"},
    {"key": "main_info", "label": "Main Info", "icon": "bi-info-circle", "url": "/dashboard/"},
    {"key": "inventory", "label": "Inventory", "icon": "bi-box", "url": "/api/inventory-page/"},
    {"key": "billing", "label": "Billing", "icon": "bi-receipt", "url": "/billing/"},
    {"key": "purchase", "label": "Purchase", "icon": "bi-bag", "url": "/api/purchase-page/"},
    {"key": "items", "label": "Items", "icon": "bi-grid-1x2", "url": "/api/items/"},
    {"key": "vendors", "label": "Vendors", "icon": "bi-people", "url": "/api/vendors-page/"},
    {"key": "orders", "label": "Orders", "icon": "bi-truck", "url": "/api/orders-page/"},
    {"key": "quotation", "label": "Quotation", "icon": "bi-file-earmark-text", "url": "/api/quotations/"},
    {"key": "leads", "label": "Lead Management", "icon": "bi-person-lines-fill", "url": "/api/leads-page/"},
    {"key": "users", "label": "Users", "icon": "bi-person-gear", "url": "/users/"},
]

MODULE_LABELS = {module["key"]: module["label"] for module in MODULES}
ALL_MODULE_KEYS = [module["key"] for module in MODULES]
ACTIONS = [
    {"key": "view", "label": "View", "icon": "bi-eye"},
    {"key": "add", "label": "Add", "icon": "bi-plus-circle"},
    {"key": "edit", "label": "Edit", "icon": "bi-pencil-square"},
    {"key": "delete", "label": "Delete", "icon": "bi-trash"},
]
ALL_ACTION_KEYS = [action["key"] for action in ACTIONS]

MODULE_PATHS = [
    ("dashboard", ("/api/home",)),
    ("main_info", ("/dashboard/", "/api/dashboard-data/")),
    ("inventory", ("/api/inventory-page/", "/api/inventory/", "/api/stock-filter/", "/api/low-stck/", "/api/low-stock-products/")),
    ("billing", ("/billing/",)),
    ("billing", ("/api/order-bills-",)),
    ("purchase", (
        "/api/purchase-page/",
        "/api/purchase-create-page/",
        "/api/purchase-details-page/",
        "/api/purchase-item",
        "/api/purchase-list",
        "/api/purchase-detail/",
        "/api/purchase-update/",
        "/api/purchase-delete/",
        "/api/all-bills",
        "/api/bills-",
    )),
    ("items", (
        "/api/items/",
        "/api/products/",
        "/api/products-update/",
        "/api/products-delete/",
        "/api/product-del/",
        "/api/upload-products",
        "/api/download-sample",
        "/api/get-products/",
        "/api/upload-image/",
        "/api/genrate-barcode",
        "/api/scan-barcode-product/",
        "/api/hsn/",
    )),
    ("vendors", ("/api/vendors-page/", "/api/vendors/", "/api/vendor-dashboard/")),
    ("orders", (
        "/api/orders-page/",
        "/api/order-ui-details/",
        "/api/create-order/",
        "/api/orders/",
        "/api/order-ui-",
        "/api/order-status/",
        "/api/order/",
        "/api/channels/",
        "/api/courier",
        "/api/customer-return",
        "/api/return-",
        "/api/wps-return/",
    )),
    ("users", ("/users/",)),
    ("quotation", ("/api/quotations/",)),
    ("leads", ("/api/leads/", "/api/leads-page/")),
]


def normalize_modules(role, modules):
    if role == UserAccessProfile.ROLE_SUPER_ADMIN:
        return ALL_MODULE_KEYS.copy()
    return [module for module in modules if module in ALL_MODULE_KEYS]


def default_action_permissions():
    return {module_key: ALL_ACTION_KEYS.copy() for module_key in ALL_MODULE_KEYS}


def normalize_action_permissions(role, post_data):
    if role == UserAccessProfile.ROLE_SUPER_ADMIN:
        return default_action_permissions()

    permissions = {}
    for module_key in ALL_MODULE_KEYS:
        selected = [
            action
            for action in post_data.getlist(f"perm__{module_key}")
            if action in ALL_ACTION_KEYS
        ]
        if selected and "view" not in selected:
            selected.insert(0, "view")
        if selected:
            permissions[module_key] = selected
    return permissions


def modules_from_action_permissions(action_permissions):
    return [
        module_key
        for module_key in ALL_MODULE_KEYS
        if "view" in (action_permissions or {}).get(module_key, [])
    ]


def get_access_profile(user):
    profile, _ = UserAccessProfile.objects.get_or_create(user=user)
    if user.is_superuser and profile.role != UserAccessProfile.ROLE_SUPER_ADMIN:
        profile.role = UserAccessProfile.ROLE_SUPER_ADMIN
        profile.modules = ALL_MODULE_KEYS.copy()
        profile.action_permissions = default_action_permissions()
        profile.save(update_fields=["role", "modules", "action_permissions", "updated_at"])
    elif profile.modules and not profile.action_permissions:
        profile.action_permissions = {
            module_key: ALL_ACTION_KEYS.copy()
            for module_key in profile.modules
            if module_key in ALL_MODULE_KEYS
        }
        profile.save(update_fields=["action_permissions", "updated_at"])
    return profile


def is_api_request(request):
    return (
        request.path.startswith("/api/") or
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in request.headers.get("accept", "")
    )


def deny_response(request, message, status_code=403):
    if is_api_request(request):
        return JsonResponse({"detail": message}, status=status_code)
    messages.error(request, message)
    if request.user.is_authenticated:
        return redirect(first_allowed_url(request.user))
    return redirect("/login/")


def database_unavailable_response(request):
    message = "Database connection unavailable. Please try again in a moment."
    if is_api_request(request):
        return JsonResponse({"detail": message}, status=503)
    return HttpResponse(
        "<!doctype html><title>Service unavailable</title>"
        "<div style='font-family:system-ui;padding:32px'>"
        "<h2>Service unavailable</h2>"
        f"<p>{message}</p>"
        "</div>",
        status=503,
    )


def has_supporting_data_access(user, path, action):
    if action != "view":
        return False
    if path.startswith("/api/vendors/"):
        return user_can_access(user, "items") or user_can_access(user, "purchase")
    if path.startswith("/api/hsn/"):
        return user_can_access(user, "items") or user_can_access(user, "purchase")
    if path.startswith("/api/products/") or path.startswith("/api/product-list/"):
        return user_can_access(user, "orders") or user_can_access(user, "purchase")
    return False


def user_can_access(user, module_key):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return get_access_profile(user).has_module(module_key)


def user_can_action(user, module_key, action):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return get_access_profile(user).has_action(module_key, action)


def first_allowed_url(user):
    if not user.is_authenticated:
        return "/login/"
    if user.is_superuser:
        return "/dashboard/"
    profile = get_access_profile(user)
    if profile.role == UserAccessProfile.ROLE_SUPER_ADMIN:
        return "/dashboard/"
    allowed = profile.modules or []
    for module in MODULES:
        if module["key"] in allowed:
            return module["url"]
    return "/logout/"


def module_for_path(path):
    for module_key, prefixes in MODULE_PATHS:
        if any(path.startswith(prefix) for prefix in prefixes):
            return module_key
    return None


def action_for_request(request):
    path = request.path
    method = request.method.upper()

    if path.startswith(("/api/leads/", "/api/leads-page/")) and method == "POST":
        bulk_action = request.POST.get("bulk_action") or request.POST.get("action")
        if path.endswith("/bulk/") and not bulk_action and "application/json" in (request.content_type or ""):
            try:
                bulk_action = json.loads(request.body.decode("utf-8") or "{}").get("action")
            except (ValueError, UnicodeDecodeError):
                bulk_action = None
        if "/delete/" in path or (path.endswith("/bulk/") and bulk_action == "delete"):
            return "delete"
        if any(token in path for token in ("/edit/", "/status/", "/convert/", "/mark-lost/")) or path.endswith("/bulk/"):
            return "edit"
        return "add"

    if method == "GET":
        if path.startswith("/api/purchase-create-page/"):
            return "edit" if request.GET.get("id") else "add"
        if "/add/" in path or "/create-" in path or path.endswith("/create-order/"):
            return "add"
        if "/edit/" in path or "/update" in path:
            return "edit"
        return "view"

    if path == "/users/" and method == "POST":
        form_action = request.POST.get("action")
        if form_action == "create_user":
            return "add"
        if form_action in {"update_access", "toggle_active"}:
            return "edit"

    if method == "POST":
        if any(token in path for token in ["/delete", "/cancel/", "-cancel/", "/soft-delete/"]):
            return "delete"
        if any(token in path for token in [
            "/update",
            "/edit/",
            "/delivered/",
            "-delivered/",
            "/pack/",
            "-pack/",
            "/shipment/",
            "-shipment/",
            "/create-shipment/",
            "/add-remark/",
            "/courier/create/",
            "/customer-return/",
            "/courier-return/",
            "/order-status/",
        ]):
            return "edit"
        return "add"
    if method in {"PUT", "PATCH"}:
        return "edit"
    if method == "DELETE":
        return "delete"
    return "view"


def attach_bearer_user(request):
    if request.user.is_authenticated:
        return
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return
    token_value = auth_header.split(" ", 1)[1].strip()
    if not token_value:
        return
    try:
        token = AccessToken(token_value)
        user_id = token.get("user_id")
        if user_id is None:
            return
        user = User.objects.filter(id=user_id, is_active=True).first()
        if user:
            request.user = user
        else:
            request.user = AnonymousUser()
    except (TokenError, ValueError, TypeError):
        request.user = AnonymousUser()


class ModuleAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        module_key = module_for_path(request.path)
        if module_key:
            try:
                attach_bearer_user(request)
                if not request.user.is_authenticated:
                    return deny_response(request, "Please login to access this module.", 401)
                action = action_for_request(request)
                if not user_can_access(request.user, module_key):
                    if has_supporting_data_access(request.user, request.path, action):
                        return self.get_response(request)
                    return deny_response(
                        request,
                        f"Aapko {MODULE_LABELS.get(module_key, 'is module')} module ka access nahi hai.",
                    )
                if not user_can_action(request.user, module_key, action):
                    return deny_response(
                        request,
                        f"Aapko {MODULE_LABELS.get(module_key, 'is module')} module me {action} permission nahi hai.",
                    )
            except OperationalError:
                return database_unavailable_response(request)
        return self.get_response(request)
