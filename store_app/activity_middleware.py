import ipaddress
import json
import logging
import time

from django.http.request import RawPostDataException

from store_app.models import Product, UserActivityLog


logger = logging.getLogger(__name__)
SENSITIVE_KEYS = {
    "password", "password1", "password2", "token", "access", "refresh",
    "authorization", "secret", "otp", "transaction_id",
}


class AutomaticUserActivityMiddleware:
    """Record authenticated API usage without a client-side logging call."""

    EXCLUDED_PATH_PREFIXES = ("/api/app/activity/", "/api/app/login/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started_at = time.monotonic()
        response = self.get_response(request)
        self._record(request, response, started_at)
        return response

    def _record(self, request, response, started_at):
        if not request.path.startswith("/api/"):
            return
        if request.path.startswith(self.EXCLUDED_PATH_PREFIXES):
            return

        user = getattr(request, "user", None)
        if not (
            getattr(user, "is_authenticated", False)
            and isinstance(getattr(user, "id", None), int)
        ):
            return

        resolver_match = getattr(request, "resolver_match", None)
        route_name = getattr(resolver_match, "view_name", "") or ""
        status_code = getattr(response, "status_code", None)
        request_data = self._request_data(request)
        response_data = self._response_data(response)
        request_data = self._add_product_names(request_data)
        response_data = self._add_product_names(response_data)
        description = self._description(
            request.method, route_name, request.path, request_data, response_data, status_code
        )
        try:
            UserActivityLog.objects.create(
                user=user,
                event=self._event_name(request.method, status_code),
                screen=route_name[:100],
                target=request.path[:150],
                metadata={
                    "description": description,
                    "method": request.method,
                    "status_code": status_code,
                    "duration_ms": round((time.monotonic() - started_at) * 1000),
                    "query_parameters": sorted(request.GET.keys()),
                    "request": request_data,
                    "result": response_data,
                },
                app_version=(request.META.get("HTTP_X_APP_VERSION") or "")[:40],
                device_id=(request.META.get("HTTP_X_DEVICE_ID") or "")[:128],
                ip_address=self._client_ip(request),
                user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:500],
            )
        except Exception:
            # Logging must never make the actual business API fail.
            logger.exception("Unable to save automatic user activity")

    @classmethod
    def _request_data(cls, request):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return {}
        if request.POST:
            data = {key: request.POST.getlist(key) for key in request.POST.keys()}
            for key, files in request.FILES.lists():
                data[key] = [file.name for file in files]
            return cls._sanitize(data)
        try:
            raw_body = request.body
        except RawPostDataException:
            return {"note": "Request body was already consumed"}
        if not raw_body:
            return {}
        try:
            return cls._sanitize(json.loads(raw_body.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"note": "Non-JSON request body", "size_bytes": len(raw_body)}

    @classmethod
    def _response_data(cls, response):
        data = getattr(response, "data", None)
        if data is None:
            return {}
        sanitized = cls._sanitize(data)
        # List APIs can return hundreds of complete objects. Keep the count and
        # recognizable names, while detail/create APIs retain their useful data.
        if isinstance(sanitized, dict) and isinstance(sanitized.get("data"), list):
            rows = sanitized["data"]
            return {
                "count": sanitized.get("count", len(rows)),
                "items": [cls._row_identity(row) for row in rows[:20]],
            }
        if isinstance(sanitized, list):
            return {
                "count": len(sanitized),
                "items": [cls._row_identity(row) for row in sanitized[:20]],
            }
        return sanitized

    @classmethod
    def _sanitize(cls, value, depth=0):
        if depth > 5:
            return "[truncated]"
        if isinstance(value, dict):
            clean = {}
            for key, item in list(value.items())[:50]:
                key_text = str(key)
                if key_text.lower() in SENSITIVE_KEYS:
                    clean[key_text] = "[redacted]"
                else:
                    clean[key_text] = cls._sanitize(item, depth + 1)
            return clean
        if isinstance(value, (list, tuple)):
            return [cls._sanitize(item, depth + 1) for item in value[:50]]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:500]

    @staticmethod
    def _row_identity(row):
        if not isinstance(row, dict):
            return row
        keys = (
            "id", "name", "product_name", "sku", "customer_name",
            "bill_number", "quantity", "status", "total_amount",
        )
        return {key: row[key] for key in keys if key in row}

    @classmethod
    def _add_product_names(cls, value):
        product_ids = set()

        def collect(node):
            if isinstance(node, dict):
                for key in ("product_id", "product"):
                    product_id = node.get(key)
                    if isinstance(product_id, int) or str(product_id).isdigit():
                        product_ids.add(int(product_id))
                for child in node.values():
                    collect(child)
            elif isinstance(node, list):
                for child in node:
                    collect(child)

        collect(value)
        if not product_ids:
            return value
        names = dict(Product.objects.filter(id__in=product_ids).values_list("id", "name"))

        def enrich(node):
            if isinstance(node, dict):
                product_id = node.get("product_id", node.get("product"))
                if str(product_id).isdigit() and int(product_id) in names:
                    node.setdefault("product_name", names[int(product_id)])
                for child in node.values():
                    enrich(child)
            elif isinstance(node, list):
                for child in node:
                    enrich(child)

        enrich(value)
        return value

    @classmethod
    def _description(cls, method, route_name, path, request_data, response_data, status_code):
        action = cls._event_name(method, status_code).replace("_", " ").title()
        entity = (route_name or path.strip("/").split("/")[-1] or "API").replace("-api", "")
        entity = entity.replace("-", " ").replace("_", " ").title()
        data = response_data if method == "GET" else request_data
        if isinstance(data, dict):
            record_id = data.get("id")
            if not record_id and isinstance(response_data, dict):
                record_id = response_data.get("id") or response_data.get("order_id")
            customer = data.get("customer_name") or data.get("name")
            items = data.get("items")
            parts = [f"{entity} {action}"]
            if record_id:
                parts.append(f"ID #{record_id}")
            if customer:
                parts.append(str(customer))
            if isinstance(items, list) and items:
                item_text = []
                for item in items[:10]:
                    if isinstance(item, dict):
                        name = item.get("product_name") or item.get("name") or item.get("sku")
                        quantity = item.get("quantity")
                        if name:
                            item_text.append(f"{name} x{quantity}" if quantity else str(name))
                if item_text:
                    parts.append("Items: " + ", ".join(item_text))
            return " | ".join(parts)
        return f"{entity} {action}"

    @staticmethod
    def _event_name(method, status_code):
        action = {
            "GET": "view",
            "POST": "create",
            "PUT": "update",
            "PATCH": "update",
            "DELETE": "delete",
        }.get(method, method.lower())
        return f"{action}_failed" if status_code is not None and status_code >= 400 else action

    @staticmethod
    def _client_ip(request):
        value = request.META.get("REMOTE_ADDR")
        try:
            return str(ipaddress.ip_address(value)) if value else None
        except ValueError:
            return None
