from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from store_app.models import UserActivityLog


DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class IsDatabaseUser(BasePermission):
    """Reject anonymous-session JWTs which have no database user id."""

    def has_permission(self, request, view):
        return bool(
            getattr(request.user, "is_authenticated", False)
            and isinstance(getattr(request.user, "id", None), int)
        )


def _limit(request):
    try:
        value = int(request.query_params.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        value = DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def _serialize(log):
    return {
        "id": log.id,
        "user_id": log.user_id,
        "username": log.user.username,
        "event": log.event,
        "description": (log.metadata or {}).get("description", ""),
        "screen": log.screen,
        "target": log.target,
        "metadata": log.metadata,
        "client_timestamp": log.client_timestamp,
        "app_version": log.app_version,
        "device_id": log.device_id,
        "ip_address": log.ip_address,
        "created_at": log.created_at,
    }


class UserActivityAPIView(APIView):
    permission_classes = [IsDatabaseUser]

    def get(self, request):
        logs = UserActivityLog.objects.filter(user=request.user).select_related("user")
        logs = _apply_filters(logs, request)[:_limit(request)]
        return Response({"results": [_serialize(log) for log in logs]})


def _apply_filters(logs, request):
    event = (request.query_params.get("event") or "").strip()
    screen = (request.query_params.get("screen") or "").strip()
    start = parse_datetime(request.query_params.get("start") or "")
    end = parse_datetime(request.query_params.get("end") or "")
    if event:
        logs = logs.filter(event=event)
    if screen:
        logs = logs.filter(screen=screen)
    if start:
        logs = logs.filter(created_at__gte=start)
    if end:
        logs = logs.filter(created_at__lte=end)
    return logs


class AllUserActivityAPIView(APIView):
    permission_classes = [IsAuthenticated, IsDatabaseUser]

    def get(self, request):
        if not (request.user.is_staff or request.user.is_superuser):
            return Response(
                {"detail": "Only admin users can view all activity logs."},
                status=status.HTTP_403_FORBIDDEN,
            )
        logs = UserActivityLog.objects.select_related("user")
        user_id = request.query_params.get("user_id")
        if user_id:
            try:
                logs = logs.filter(user_id=int(user_id))
            except (TypeError, ValueError):
                return Response({"user_id": ["Must be an integer."]}, status=400)
        logs = _apply_filters(logs, request)[:_limit(request)]
        return Response({"results": [_serialize(log) for log in logs]})
