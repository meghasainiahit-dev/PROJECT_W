import csv
import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Min, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_POST
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .models import (
    Lead, LeadActivity, LeadConversion, LeadFollowUp, LeadNote, Product,
    LeadStatusHistory,
)


LEAD_FIELDS = (
    "full_name", "shipping_name", "country_code", "phone", "whatsapp_number",
    "shipping_phone", "email", "company_name",
    "designation", "source", "priority", "status", "tags", "address",
    "city", "state", "country", "pincode", "shipping_address1",
    "shipping_address2", "shipping_city", "shipping_zip",
    "shipping_province", "shipping_province_name", "shipping_country", "notes",
)
ACTIVE_STATUSES = [choice[0] for choice in Lead.STATUS_CHOICES if choice[0] not in {Lead.STATUS_CONVERTED, Lead.STATUS_LOST}]

# Kept locally so the lead form does not depend on an external service.  India
# stays first because it is the application's default market; remaining entries
# are alphabetical and the country selector keeps the dial code synchronized.
COUNTRY_DIAL_CODES = [
    ("India", "+91"), ("Afghanistan", "+93"), ("Albania", "+355"),
    ("Algeria", "+213"), ("Argentina", "+54"), ("Australia", "+61"),
    ("Austria", "+43"), ("Bahrain", "+973"), ("Bangladesh", "+880"),
    ("Belgium", "+32"), ("Bhutan", "+975"), ("Brazil", "+55"),
    ("Canada", "+1"), ("China", "+86"), ("Denmark", "+45"),
    ("Egypt", "+20"), ("Finland", "+358"), ("France", "+33"),
    ("Germany", "+49"), ("Greece", "+30"), ("Hong Kong", "+852"),
    ("Indonesia", "+62"), ("Ireland", "+353"), ("Israel", "+972"),
    ("Italy", "+39"), ("Japan", "+81"), ("Kenya", "+254"),
    ("Kuwait", "+965"), ("Malaysia", "+60"), ("Maldives", "+960"),
    ("Mauritius", "+230"), ("Mexico", "+52"), ("Myanmar", "+95"),
    ("Nepal", "+977"), ("Netherlands", "+31"), ("New Zealand", "+64"),
    ("Nigeria", "+234"), ("Norway", "+47"), ("Oman", "+968"),
    ("Pakistan", "+92"), ("Philippines", "+63"), ("Poland", "+48"),
    ("Portugal", "+351"), ("Qatar", "+974"), ("Russia", "+7"),
    ("Saudi Arabia", "+966"), ("Singapore", "+65"), ("South Africa", "+27"),
    ("South Korea", "+82"), ("Spain", "+34"), ("Sri Lanka", "+94"),
    ("Sweden", "+46"), ("Switzerland", "+41"), ("Taiwan", "+886"),
    ("Thailand", "+66"), ("Turkey", "+90"), ("United Arab Emirates", "+971"),
    ("United Kingdom", "+44"), ("United States", "+1"), ("Vietnam", "+84"),
]


class MiddlewareUserAuthentication(BaseAuthentication):
    """Use the session/JWT user resolved by the existing access middleware."""

    def authenticate(self, request):
        user = getattr(request._request, "user", None)
        if user and user.is_authenticated:
            return user, None
        return None


class LeadAPIView(APIView):
    authentication_classes = [MiddlewareUserAuthentication]
    permission_classes = [IsAuthenticated]


def _user(request):
    return request.user if getattr(request.user, "is_authenticated", False) else None


def _payload(request):
    if "application/json" in (request.content_type or ""):
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}
    return request.POST


def _choice_values(choices):
    return {value for value, _label in choices}


def _bounded_int(value, default, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def _product_ids_from_data(data):
    if hasattr(data, "getlist"):
        raw_ids = data.getlist("product_ids") or data.getlist("products")
    else:
        raw_ids = data.get("product_ids", data.get("products", []))
    if isinstance(raw_ids, str):
        raw_ids = [value.strip() for value in raw_ids.split(",") if value.strip()]
    if not isinstance(raw_ids, (list, tuple)):
        return []
    return [int(value) for value in raw_ids if str(value).isdigit()]


def _validation_errors(data, partial=False):
    errors = {}
    if not partial or "shipping_name" in data or "full_name" in data:
        if not str(data.get("shipping_name", data.get("full_name", ""))).strip():
            errors["shipping_name"] = "Shipping name is required."
    if not partial or "phone" in data:
        if not str(data.get("phone", "")).strip():
            errors["phone"] = "Phone number is required."
    if "country_code" in data:
        code = str(data.get("country_code", "")).strip()
        if not code.startswith("+") or not code[1:].isdigit():
            errors["country_code"] = "Select a valid country code."
    for field, choices in (("source", Lead.SOURCE_CHOICES), ("priority", Lead.PRIORITY_CHOICES), ("status", Lead.STATUS_CHOICES)):
        if field in data and data.get(field) not in _choice_values(choices):
            errors[field] = f"Select a valid {field.replace('_', ' ')}."
    return errors


def _set_lead_fields(lead, data, request, creating=False):
    old_status = lead.status
    old_assignee = lead.assigned_to_id
    for field in LEAD_FIELDS:
        if field in data:
            setattr(lead, field, str(data.get(field, "")).strip())

    # New shipping/customer fields are canonical; keep legacy fields populated
    # so existing lists, searches and integrations continue to work unchanged.
    if "shipping_name" in data:
        lead.full_name = str(data.get("shipping_name", "")).strip()
    elif "full_name" in data:
        lead.shipping_name = str(data.get("full_name", "")).strip()
    if "shipping_phone" in data:
        lead.whatsapp_number = str(data.get("shipping_phone", "")).strip()
    if "shipping_address1" in data or "shipping_address2" in data:
        lead.address = "\n".join(filter(None, [
            str(data.get("shipping_address1", "")).strip(),
            str(data.get("shipping_address2", "")).strip(),
        ]))
    for shipping_field, legacy_field in (
        ("shipping_city", "city"), ("shipping_zip", "pincode"),
        ("shipping_province_name", "state"), ("shipping_country", "country"),
    ):
        if shipping_field in data:
            setattr(lead, legacy_field, str(data.get(shipping_field, "")).strip())
    if "assigned_to" in data or "assigned_to_id" in data:
        raw_id = data.get("assigned_to", data.get("assigned_to_id"))
        lead.assigned_to = User.objects.filter(pk=raw_id, is_active=True).first() if raw_id else None
    actor = _user(request)
    if creating:
        lead.created_by = actor
    lead.updated_by = actor
    lead.save()
    if "product_ids" in data or "products" in data:
        lead.products.set(Product.objects.filter(pk__in=_product_ids_from_data(data)))

    if creating:
        LeadActivity.objects.create(lead=lead, event="created", title="Lead Created", actor=actor)
    else:
        LeadActivity.objects.create(lead=lead, event="updated", title="Lead Updated", actor=actor)
    if old_assignee != lead.assigned_to_id:
        name = lead.assigned_to.get_full_name() or lead.assigned_to.username if lead.assigned_to else "Unassigned"
        LeadActivity.objects.create(
            lead=lead, event="assigned", title="Assigned to Employee",
            description=f"Assigned to {name}", actor=actor,
            metadata={"assigned_to_id": lead.assigned_to_id, "assigned_to": name},
        )
    if not creating and old_status != lead.status:
        _record_status_change(lead, old_status, lead.status, actor)
    return lead


def _record_status_change(lead, old_status, new_status, actor, reason=""):
    labels = dict(Lead.STATUS_CHOICES)
    LeadStatusHistory.objects.create(
        lead=lead, old_status=old_status, new_status=new_status,
        changed_by=actor, reason=reason,
    )
    event = "proposal_sent" if new_status == Lead.STATUS_PROPOSAL_SENT else "status_changed"
    title = "Proposal Sent" if event == "proposal_sent" else "Status Changed"
    LeadActivity.objects.create(
        lead=lead, event=event, title=title,
        description=f"{labels.get(old_status, old_status)} → {labels.get(new_status, new_status)}",
        metadata={"old_status": old_status, "new_status": new_status}, actor=actor,
    )


@transaction.atomic
def change_status(lead, new_status, request, reason=""):
    if new_status not in _choice_values(Lead.STATUS_CHOICES):
        raise ValueError("Select a valid status.")
    if new_status == Lead.STATUS_CONVERTED:
        raise ValueError("Use Convert Lead to capture conversion details.")
    if new_status == Lead.STATUS_LOST:
        raise ValueError("Use Mark Lost to capture a reason.")
    old_status = lead.status
    if old_status != new_status:
        lead.status = new_status
        lead.updated_by = _user(request)
        lead.save(update_fields=["status", "updated_by", "updated_at"])
        _record_status_change(lead, old_status, new_status, _user(request), reason)
    return lead


@transaction.atomic
def mark_lost(lead, data, request):
    reason = str(data.get("lost_reason", "")).strip()
    if reason not in _choice_values(Lead.LOST_REASON_CHOICES):
        raise ValueError("Select a valid lost reason.")
    old_status = lead.status
    lead.status = Lead.STATUS_LOST
    lead.lost_reason = reason
    lead.lost_notes = str(data.get("notes", "")).strip()
    lead.lost_at = timezone.now()
    lead.lost_by = _user(request)
    lead.updated_by = _user(request)
    lead.save(update_fields=["status", "lost_reason", "lost_notes", "lost_at", "lost_by", "updated_by", "updated_at"])
    if old_status != lead.status:
        _record_status_change(lead, old_status, lead.status, _user(request), dict(Lead.LOST_REASON_CHOICES)[reason])
    LeadActivity.objects.create(
        lead=lead, event="lost", title="Lead Lost",
        description=dict(Lead.LOST_REASON_CHOICES)[reason], actor=_user(request),
        metadata={"reason": reason},
    )
    return lead


@transaction.atomic
def convert_lead(lead, data, request):
    conversion_date = parse_date(str(data.get("conversion_date", "")))
    product_service = str(data.get("product_service", "")).strip()
    if not conversion_date or not product_service:
        raise ValueError("Conversion date and product / service are required.")
    try:
        amount = Decimal(str(data.get("deal_amount", "0") or "0"))
    except InvalidOperation:
        raise ValueError("Enter a valid deal amount.")
    if amount < 0:
        raise ValueError("Deal amount cannot be negative.")
    payment_status = str(data.get("payment_status", "pending"))
    if payment_status not in _choice_values(LeadConversion.PAYMENT_STATUS_CHOICES):
        raise ValueError("Select a valid payment status.")
    conversion, _ = LeadConversion.objects.update_or_create(
        lead=lead,
        defaults={
            "conversion_date": conversion_date, "product_service": product_service,
            "deal_amount": amount, "payment_status": payment_status,
            "notes": str(data.get("notes", "")).strip(), "converted_by": _user(request),
        },
    )
    old_status = lead.status
    lead.status = Lead.STATUS_CONVERTED
    lead.updated_by = _user(request)
    lead.save(update_fields=["status", "updated_by", "updated_at"])
    if old_status != lead.status:
        _record_status_change(lead, old_status, lead.status, _user(request))
    LeadActivity.objects.create(
        lead=lead, event="converted", title="Lead Converted",
        description=f"{product_service} · ₹{amount:,.2f}", actor=_user(request),
        metadata={"conversion_id": conversion.id, "deal_amount": str(amount)},
    )
    return conversion


def _create_follow_up(lead, data, request):
    date_value = parse_date(str(data.get("follow_up_date", "")))
    time_value = parse_time(str(data.get("follow_up_time", "")))
    type_value = str(data.get("follow_up_type", ""))
    if not date_value or not time_value or type_value not in _choice_values(LeadFollowUp.TYPE_CHOICES):
        raise ValueError("Date, time and a valid follow-up type are required.")
    assigned_id = data.get("assigned_to", data.get("assigned_to_id"))
    follow_up = LeadFollowUp.objects.create(
        lead=lead, follow_up_date=date_value, follow_up_time=time_value,
        follow_up_type=type_value, notes=str(data.get("notes", "")).strip(),
        assigned_to=User.objects.filter(pk=assigned_id, is_active=True).first() if assigned_id else lead.assigned_to,
        created_by=_user(request),
    )
    LeadActivity.objects.create(
        lead=lead, event="follow_up_added", title="Follow-up Added",
        description=f"{follow_up.get_follow_up_type_display()} scheduled for {date_value:%d %b %Y} at {time_value:%H:%M}",
        actor=_user(request), metadata={"follow_up_id": follow_up.id},
    )
    return follow_up


def _serialize_follow_up(item):
    return {
        "id": item.id, "lead_id": item.lead_id,
        "follow_up_date": item.follow_up_date.isoformat(),
        "follow_up_time": item.follow_up_time.strftime("%H:%M"),
        "follow_up_type": item.follow_up_type, "follow_up_type_display": item.get_follow_up_type_display(),
        "status": item.status, "status_display": item.get_status_display(),
        "notes": item.notes, "assigned_to": item.assigned_to_id,
        "assigned_to_name": (item.assigned_to.get_full_name() or item.assigned_to.username) if item.assigned_to else None,
    }


def _serialize_activity(row):
    return {
        "id": row.id, "event": row.event, "title": row.title,
        "description": row.description, "metadata": row.metadata,
        "actor": row.actor_id,
        "actor_name": (row.actor.get_full_name() or row.actor.username) if row.actor else None,
        "created_at": row.created_at.isoformat(),
    }


def _serialize_note(row):
    return {
        "id": row.id, "lead": row.lead_id, "note": row.note,
        "created_by": row.created_by_id,
        "created_by_name": (row.created_by.get_full_name() or row.created_by.username) if row.created_by else None,
        "created_at": row.created_at.isoformat(),
    }


def lead_statistics():
    today = timezone.localdate()
    totals = Lead.objects.filter(is_deleted=False).aggregate(
        total=Count("id"), new=Count("id", filter=Q(status=Lead.STATUS_NEW)),
        active=Count("id", filter=Q(status__in=ACTIVE_STATUSES)),
        converted=Count("id", filter=Q(status=Lead.STATUS_CONVERTED)),
        lost=Count("id", filter=Q(status=Lead.STATUS_LOST)),
    )
    totals["follow_ups_today"] = LeadFollowUp.objects.filter(
        follow_up_date=today, status="upcoming", lead__is_deleted=False,
    ).count()
    totals["overdue_follow_ups"] = LeadFollowUp.objects.filter(
        follow_up_date__lt=today, status="upcoming", lead__is_deleted=False,
    ).count()
    totals["conversion_rate"] = round(
        totals["converted"] / totals["total"] * 100, 1,
    ) if totals["total"] else 0
    return totals


def serialize_lead(lead, detailed=False):
    prefetched = getattr(lead, "_prefetched_follow_ups", None)
    next_item = prefetched[0] if prefetched else None
    if prefetched is None:
        next_item = lead.follow_ups.filter(
            status="upcoming", follow_up_date__gte=timezone.localdate()
        ).select_related("assigned_to").first()
    data = {
        "id": lead.id, "lead_id": lead.lead_id, "full_name": lead.full_name,
        "shipping_name": lead.shipping_name or lead.full_name,
        "country_code": lead.country_code, "phone": lead.phone,
        "shipping_phone": lead.shipping_phone, "whatsapp_number": lead.whatsapp_number,
        "email": lead.email, "company_name": lead.company_name, "designation": lead.designation,
        "source": lead.source, "source_display": lead.get_source_display(),
        "priority": lead.priority, "priority_display": lead.get_priority_display(),
        "assigned_to": lead.assigned_to_id,
        "assigned_to_name": (lead.assigned_to.get_full_name() or lead.assigned_to.username) if lead.assigned_to else None,
        "status": lead.status, "status_display": lead.get_status_display(),
        "tags": [tag.strip() for tag in lead.tags.split(",") if tag.strip()],
        "address": lead.address, "city": lead.city, "state": lead.state,
        "country": lead.country, "pincode": lead.pincode,
        "shipping_address1": lead.shipping_address1,
        "shipping_address2": lead.shipping_address2,
        "shipping_city": lead.shipping_city, "shipping_zip": lead.shipping_zip,
        "shipping_province": lead.shipping_province,
        "shipping_province_name": lead.shipping_province_name,
        "shipping_country": lead.shipping_country,
        "products": [{
            "id": product.id, "name": product.name, "sku": product.sku,
            "size": product.size, "color": product.color,
            "retailer_price": str(product.retailer_price),
            "wholesale_price": str(product.wholesale_price),
        } for product in lead.products.all()],
        "notes": lead.notes,
        "next_follow_up": _serialize_follow_up(next_item) if next_item else None,
        "created_at": lead.created_at.isoformat(), "updated_at": lead.updated_at.isoformat(),
        "updated_by": lead.updated_by_id,
        "updated_by_name": (lead.updated_by.get_full_name() or lead.updated_by.username) if lead.updated_by else None,
    }
    if detailed:
        data["activities"] = [_serialize_activity(row) for row in lead.activities.select_related("actor").all()]
        data["follow_ups"] = [_serialize_follow_up(row) for row in lead.follow_ups.select_related("assigned_to").all()]
        data["lead_notes"] = [_serialize_note(row) for row in lead.lead_notes.select_related("created_by").all()]
        if hasattr(lead, "conversion"):
            data["conversion"] = {
                "conversion_date": lead.conversion.conversion_date.isoformat(),
                "product_service": lead.conversion.product_service,
                "deal_amount": str(lead.conversion.deal_amount),
                "payment_status": lead.conversion.payment_status,
                "notes": lead.conversion.notes, "converted_by": lead.conversion.converted_by_id,
            }
    return data


def filtered_leads(request):
    leads = Lead.objects.filter(is_deleted=False).select_related("assigned_to", "updated_by").prefetch_related("products")
    search = request.GET.get("search", "").strip()
    if search:
        leads = leads.filter(
            Q(full_name__icontains=search) | Q(shipping_name__icontains=search)
            | Q(phone__icontains=search) | Q(shipping_phone__icontains=search)
            | Q(email__icontains=search) | Q(shipping_city__icontains=search)
            | Q(shipping_country__icontains=search) | Q(products__name__icontains=search)
            | Q(products__sku__icontains=search)
        ).distinct()
    for param, field in (("status", "status"), ("priority", "priority"), ("source", "source"), ("assigned_to", "assigned_to_id")):
        value = request.GET.get(param)
        if value and (param != "assigned_to" or str(value).isdigit()):
            leads = leads.filter(**{field: value})
    view = request.GET.get("view", "all")
    if view == "active":
        leads = leads.filter(status__in=ACTIVE_STATUSES)
    elif view == "converted":
        leads = leads.filter(status=Lead.STATUS_CONVERTED)
    elif view == "lost":
        leads = leads.filter(status=Lead.STATUS_LOST)
    date_from, date_to = parse_date(request.GET.get("date_from", "")), parse_date(request.GET.get("date_to", ""))
    if date_from:
        leads = leads.filter(created_at__date__gte=date_from)
    if date_to:
        leads = leads.filter(created_at__date__lte=date_to)
    sort_map = {
        "created_at": "created_at", "-created_at": "-created_at", "name": "full_name", "-name": "-full_name",
        "status": "status", "-status": "-status", "priority": "priority", "-priority": "-priority",
        "next_follow_up": "next_follow_up_date", "-next_follow_up": "-next_follow_up_date",
    }
    leads = leads.annotate(
        next_follow_up_date=Min("follow_ups__follow_up_date", filter=Q(follow_ups__status="upcoming", follow_ups__follow_up_date__gte=timezone.localdate()))
    ).prefetch_related(Prefetch(
        "follow_ups",
        queryset=LeadFollowUp.objects.filter(status="upcoming", follow_up_date__gte=timezone.localdate()).select_related("assigned_to").order_by("follow_up_date", "follow_up_time", "id"),
        to_attr="_prefetched_follow_ups",
    )).order_by(sort_map.get(request.GET.get("sort", "-created_at"), "-created_at"), "-id")
    return leads


class LeadListCreateAPI(LeadAPIView):
    def get(self, request):
        qs = filtered_leads(request)
        paginator = Paginator(qs, _bounded_int(request.GET.get("page_size"), 25, 1, 100))
        page = paginator.get_page(request.GET.get("page"))
        return JsonResponse({
            "count": paginator.count, "page": page.number, "pages": paginator.num_pages,
            "results": [serialize_lead(row) for row in page.object_list],
        })

    @transaction.atomic
    def post(self, request):
        data = _payload(request)
        if data.get("status") in {Lead.STATUS_CONVERTED, Lead.STATUS_LOST}:
            return JsonResponse({"detail": "Create the lead first, then use Convert Lead or Mark Lost."}, status=400)
        errors = _validation_errors(data)
        if errors:
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=400)
        lead = _set_lead_fields(Lead(), data, request, creating=True)
        return JsonResponse(serialize_lead(lead, True), status=201)


class LeadOptionsAPI(LeadAPIView):
    def get(self, request):
        return JsonResponse({
            "statuses": [{"value": value, "label": label} for value, label in Lead.STATUS_CHOICES],
            "priorities": [{"value": value, "label": label} for value, label in Lead.PRIORITY_CHOICES],
            "sources": [{"value": value, "label": label} for value, label in Lead.SOURCE_CHOICES],
            "lost_reasons": [{"value": value, "label": label} for value, label in Lead.LOST_REASON_CHOICES],
            "follow_up_types": [{"value": value, "label": label} for value, label in LeadFollowUp.TYPE_CHOICES],
            "follow_up_statuses": [{"value": value, "label": label} for value, label in LeadFollowUp.STATUS_CHOICES],
            "payment_statuses": [{"value": value, "label": label} for value, label in LeadConversion.PAYMENT_STATUS_CHOICES],
            "employees": [{
                "id": employee.id,
                "name": employee.get_full_name() or employee.username,
                "username": employee.username,
            } for employee in User.objects.filter(is_active=True).order_by("first_name", "username")],
            "countries": [{"name": country, "dial_code": code} for country, code in COUNTRY_DIAL_CODES],
            "products": [{
                "id": product.id, "name": product.name, "sku": product.sku,
                "size": product.size, "color": product.color,
                "retailer_price": str(product.retailer_price),
                "wholesale_price": str(product.wholesale_price),
            } for product in Product.objects.select_related("vendor").order_by("name", "id")],
        })


class LeadStatsAPI(LeadAPIView):
    def get(self, request):
        return JsonResponse(lead_statistics())


class LeadFollowUpListAPI(LeadAPIView):
    def get(self, request):
        today = timezone.localdate()
        qs = LeadFollowUp.objects.filter(lead__is_deleted=False).select_related("lead", "assigned_to")
        section = request.GET.get("section", "")
        if section == "overdue":
            qs = qs.filter(status="upcoming", follow_up_date__lt=today)
        elif section == "today":
            qs = qs.filter(status="upcoming", follow_up_date=today)
        elif section == "upcoming":
            qs = qs.filter(status="upcoming", follow_up_date__gt=today)
        elif section == "completed":
            qs = qs.filter(status="completed").order_by("-completed_at", "-id")
        elif request.GET.get("status") in _choice_values(LeadFollowUp.STATUS_CHOICES):
            qs = qs.filter(status=request.GET["status"])
        if str(request.GET.get("lead", "")).isdigit():
            qs = qs.filter(lead_id=request.GET["lead"])
        if str(request.GET.get("assigned_to", "")).isdigit():
            qs = qs.filter(assigned_to_id=request.GET["assigned_to"])
        date_from = parse_date(request.GET.get("date_from", ""))
        date_to = parse_date(request.GET.get("date_to", ""))
        if date_from:
            qs = qs.filter(follow_up_date__gte=date_from)
        if date_to:
            qs = qs.filter(follow_up_date__lte=date_to)
        paginator = Paginator(qs, _bounded_int(request.GET.get("page_size"), 25, 1, 100))
        page = paginator.get_page(request.GET.get("page"))
        return JsonResponse({
            "count": paginator.count, "page": page.number, "pages": paginator.num_pages,
            "results": [{**_serialize_follow_up(item), "lead_name": item.lead.full_name, "lead_code": item.lead.lead_id} for item in page.object_list],
        })


class LeadDetailAPI(LeadAPIView):
    def _lead(self, pk):
        return get_object_or_404(Lead.objects.select_related("assigned_to", "updated_by"), pk=pk, is_deleted=False)

    def get(self, request, pk):
        return JsonResponse(serialize_lead(self._lead(pk), True))

    @transaction.atomic
    def put(self, request, pk):
        lead, data = self._lead(pk), _payload(request)
        if data.get("status") in {Lead.STATUS_CONVERTED, Lead.STATUS_LOST} and data.get("status") != lead.status:
            return JsonResponse({"detail": "Use Convert Lead or Mark Lost to capture the required details."}, status=400)
        errors = _validation_errors(data, partial=False)
        if errors:
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=400)
        _set_lead_fields(lead, data, request)
        return JsonResponse(serialize_lead(lead, True))

    patch = put

    def delete(self, request, pk):
        lead = self._lead(pk)
        lead.is_deleted = True
        lead.updated_by = _user(request)
        lead.save(update_fields=["is_deleted", "updated_by", "updated_at"])
        return JsonResponse({"detail": "Lead deleted successfully."})


class LeadActionAPI(LeadAPIView):
    def post(self, request, pk, action):
        lead = get_object_or_404(Lead, pk=pk, is_deleted=False)
        data = _payload(request)
        try:
            if action == "follow-up":
                result = _serialize_follow_up(_create_follow_up(lead, data, request))
            elif action == "note":
                note_text = str(data.get("note", "")).strip()
                if not note_text:
                    raise ValueError("Note is required.")
                note = LeadNote.objects.create(lead=lead, note=note_text, created_by=_user(request))
                LeadActivity.objects.create(lead=lead, event="note_added", title="Note Added", description=note_text, actor=_user(request), metadata={"note_id": note.id})
                result = {"id": note.id, "note": note.note, "created_at": note.created_at.isoformat()}
            elif action == "convert":
                conversion = convert_lead(lead, data, request)
                result = {"id": conversion.id, "lead": serialize_lead(lead, True)}
            elif action == "mark-lost":
                mark_lost(lead, data, request)
                result = serialize_lead(lead, True)
            elif action == "status":
                change_status(lead, str(data.get("status", "")), request, str(data.get("reason", "")))
                result = serialize_lead(lead, True)
            else:
                return JsonResponse({"detail": "Unknown action."}, status=404)
        except ValueError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        return JsonResponse(result, status=201 if action in {"follow-up", "note", "convert"} else 200)


class LeadRelatedAPI(LeadAPIView):
    def get(self, request, pk, resource):
        lead = get_object_or_404(Lead, pk=pk, is_deleted=False)
        if resource == "activities":
            rows = [_serialize_activity(row) for row in lead.activities.select_related("actor").all()]
        elif resource == "follow-ups":
            rows = [_serialize_follow_up(row) for row in lead.follow_ups.select_related("assigned_to").all()]
        elif resource == "notes":
            rows = [_serialize_note(row) for row in lead.lead_notes.select_related("created_by").all()]
        elif resource == "status-history":
            labels = dict(Lead.STATUS_CHOICES)
            rows = [{
                "id": row.id, "old_status": row.old_status,
                "old_status_display": labels.get(row.old_status, row.old_status),
                "new_status": row.new_status,
                "new_status_display": labels.get(row.new_status, row.new_status),
                "reason": row.reason, "changed_by": row.changed_by_id,
                "changed_by_name": (row.changed_by.get_full_name() or row.changed_by.username) if row.changed_by else None,
                "created_at": row.created_at.isoformat(),
            } for row in lead.status_history.select_related("changed_by").all()]
        else:
            return JsonResponse({"detail": "Unknown related resource."}, status=404)
        return JsonResponse({"count": len(rows), "results": rows})


class LeadBulkAPI(LeadAPIView):
    def post(self, request):
        data = _payload(request)
        raw_ids = data.get("lead_ids", [])
        if not isinstance(raw_ids, list):
            return JsonResponse({"detail": "lead_ids must be an array."}, status=400)
        ids = [value for value in raw_ids if str(value).isdigit()]
        leads = list(Lead.objects.filter(id__in=ids, is_deleted=False))
        if not leads:
            return JsonResponse({"detail": "Select at least one valid lead."}, status=400)
        action, value = str(data.get("action", "")), data.get("value")
        try:
            if action == "status":
                if value in {Lead.STATUS_CONVERTED, Lead.STATUS_LOST}:
                    raise ValueError("Convert or mark leads lost individually to capture required details.")
                for lead in leads:
                    change_status(lead, str(value or ""), request)
            elif action == "priority":
                if value not in _choice_values(Lead.PRIORITY_CHOICES):
                    raise ValueError("Select a valid priority.")
                for lead in leads:
                    lead.priority, lead.updated_by = value, _user(request)
                    lead.save(update_fields=["priority", "updated_by", "updated_at"])
                    LeadActivity.objects.create(lead=lead, event="updated", title="Lead Updated", description=f"Priority changed to {lead.get_priority_display()}", actor=_user(request))
            elif action == "assign":
                if value and not str(value).isdigit():
                    raise ValueError("Select a valid employee.")
                assignee = User.objects.filter(pk=value, is_active=True).first() if value else None
                if value and not assignee:
                    raise ValueError("Employee not found.")
                for lead in leads:
                    lead.assigned_to, lead.updated_by = assignee, _user(request)
                    lead.save(update_fields=["assigned_to", "updated_by", "updated_at"])
                    name = assignee.get_full_name() or assignee.username if assignee else "Unassigned"
                    LeadActivity.objects.create(lead=lead, event="assigned", title="Assigned to Employee", description=f"Assigned to {name}", actor=_user(request), metadata={"assigned_to_id": assignee.id if assignee else None})
            elif action == "delete":
                Lead.objects.filter(id__in=[lead.id for lead in leads]).update(is_deleted=True, updated_by=_user(request), updated_at=timezone.now())
            else:
                raise ValueError("Select a valid bulk action: status, priority, assign or delete.")
        except ValueError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        return JsonResponse({"detail": f"{len(leads)} lead(s) updated.", "count": len(leads), "action": action})


class FollowUpDetailAPI(LeadAPIView):
    def get(self, request, pk):
        return JsonResponse(_serialize_follow_up(get_object_or_404(
            LeadFollowUp.objects.select_related("lead", "assigned_to"), pk=pk, lead__is_deleted=False,
        )))

    def put(self, request, pk):
        item = get_object_or_404(LeadFollowUp.objects.select_related("lead"), pk=pk, lead__is_deleted=False)
        data = _payload(request)
        date_value = parse_date(str(data.get("follow_up_date", item.follow_up_date)))
        time_value = parse_time(str(data.get("follow_up_time", item.follow_up_time)))
        type_value = str(data.get("follow_up_type", item.follow_up_type))
        status_value = str(data.get("status", item.status))
        if not date_value or not time_value or type_value not in _choice_values(LeadFollowUp.TYPE_CHOICES):
            return JsonResponse({"detail": "Enter a valid date, time and follow-up type."}, status=400)
        if status_value not in _choice_values(LeadFollowUp.STATUS_CHOICES):
            return JsonResponse({"detail": "Select a valid follow-up status."}, status=400)
        previous = item.status
        assigned_id = data.get("assigned_to", data.get("assigned_to_id", item.assigned_to_id))
        item.follow_up_date, item.follow_up_time = date_value, time_value
        item.follow_up_type, item.status = type_value, status_value
        item.notes = str(data.get("notes", item.notes)).strip()
        item.assigned_to = User.objects.filter(pk=assigned_id, is_active=True).first() if assigned_id else None
        item.completed_at = timezone.now() if status_value == "completed" else None
        item.save()
        LeadActivity.objects.create(
            lead=item.lead,
            event="follow_up_completed" if previous != "completed" and status_value == "completed" else "updated",
            title="Follow-up Completed" if previous != "completed" and status_value == "completed" else "Follow-up Updated",
            description=f"{item.get_follow_up_type_display()} · {item.get_status_display()}",
            actor=_user(request), metadata={"follow_up_id": item.id, "status": status_value},
        )
        return JsonResponse(_serialize_follow_up(item))

    patch = put

    def delete(self, request, pk):
        item = get_object_or_404(LeadFollowUp.objects.select_related("lead"), pk=pk, lead__is_deleted=False)
        lead, item_id, label = item.lead, item.id, item.get_follow_up_type_display()
        item.delete()
        LeadActivity.objects.create(
            lead=lead, event="updated", title="Follow-up Deleted",
            description=label, actor=_user(request), metadata={"follow_up_id": item_id},
        )
        return JsonResponse({"detail": "Follow-up deleted successfully."})


def lead_list_page(request):
    qs = filtered_leads(request)
    paginator = Paginator(qs, _bounded_int(request.GET.get("per_page"), 25, 10, 100))
    page_obj = paginator.get_page(request.GET.get("page"))
    context = _base_context(request)
    context.update({"page_obj": page_obj, "paginator": paginator, "totals": lead_statistics()})
    return render(request, "lead_management/list.html", context)


def lead_form_page(request, pk=None):
    lead = get_object_or_404(Lead, pk=pk, is_deleted=False) if pk else None
    if request.method == "POST":
        if request.POST.get("status") in {Lead.STATUS_CONVERTED, Lead.STATUS_LOST} and (not lead or request.POST.get("status") != lead.status):
            messages.error(request, "Use Convert Lead or Mark Lost to capture the required details.")
            context = _base_context(request)
            context.update({"lead": lead, "form_data": request.POST})
            return render(request, "lead_management/form.html", context)
        errors = _validation_errors(request.POST)
        if not errors:
            with transaction.atomic():
                lead = _set_lead_fields(lead or Lead(), request.POST, request, creating=not bool(pk))
            messages.success(request, "Lead updated successfully." if pk else "Lead created successfully.")
            return redirect("lead-detail-page", pk=lead.pk)
        for message in errors.values():
            messages.error(request, message)
    context = _base_context(request)
    selected_ids = set(
        _product_ids_from_data(request.POST)
        if request.method == "POST"
        else (lead.products.values_list("id", flat=True) if lead else [])
    )
    products = list(Product.objects.select_related("vendor").order_by("name", "id"))
    for product in products:
        product.is_selected_for_lead = product.id in selected_ids
    context.update({
        "lead": lead, "form_data": request.POST if request.method == "POST" else None,
        "products": products,
    })
    return render(request, "lead_management/form.html", context)


def lead_detail_page(request, pk):
    lead = get_object_or_404(
        Lead.objects.select_related("assigned_to", "created_by", "updated_by").prefetch_related("products"),
        pk=pk, is_deleted=False,
    )
    context = _base_context(request)
    context.update({
        "lead": lead,
        "activities": lead.activities.select_related("actor").all(),
        "follow_ups": lead.follow_ups.select_related("assigned_to").all(),
        "notes": lead.lead_notes.select_related("created_by").all(),
        "today": timezone.localdate(),
    })
    return render(request, "lead_management/detail.html", context)


def follow_ups_page(request):
    today = timezone.localdate()
    qs = LeadFollowUp.objects.filter(lead__is_deleted=False).select_related("lead", "assigned_to")
    context = _base_context(request)
    context.update({
        "overdue": qs.filter(status="upcoming", follow_up_date__lt=today),
        "today_follow_ups": qs.filter(status="upcoming", follow_up_date=today),
        "upcoming": qs.filter(status="upcoming", follow_up_date__gt=today),
        "completed": qs.filter(status="completed").order_by("-completed_at", "-id")[:100],
    })
    return render(request, "lead_management/follow_ups.html", context)


@require_POST
def lead_web_action(request, pk, action):
    lead = get_object_or_404(Lead, pk=pk, is_deleted=False)
    try:
        if action == "status":
            change_status(lead, request.POST.get("status", ""), request)
            messages.success(request, "Lead status updated.")
        elif action == "follow-up":
            _create_follow_up(lead, request.POST, request)
            messages.success(request, "Follow-up scheduled.")
        elif action == "note":
            note_text = request.POST.get("note", "").strip()
            if not note_text:
                raise ValueError("Note is required.")
            note = LeadNote.objects.create(lead=lead, note=note_text, created_by=_user(request))
            LeadActivity.objects.create(lead=lead, event="note_added", title="Note Added", description=note_text, actor=_user(request), metadata={"note_id": note.id})
            messages.success(request, "Note added.")
        elif action == "convert":
            convert_lead(lead, request.POST, request)
            messages.success(request, "Lead converted successfully.")
        elif action == "mark-lost":
            mark_lost(lead, request.POST, request)
            messages.success(request, "Lead marked as lost.")
        elif action == "delete":
            lead.is_deleted = True
            lead.updated_by = _user(request)
            lead.save(update_fields=["is_deleted", "updated_by", "updated_at"])
            messages.success(request, "Lead deleted successfully.")
            return redirect("lead-list-page")
        else:
            raise ValueError("Unknown action.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("lead-detail-page", pk=pk)


@require_POST
def follow_up_web_status(request, pk):
    item = get_object_or_404(LeadFollowUp.objects.select_related("lead"), pk=pk)
    status_value = request.POST.get("status", "")
    if status_value not in _choice_values(LeadFollowUp.STATUS_CHOICES):
        messages.error(request, "Select a valid follow-up status.")
    else:
        previous = item.status
        item.status = status_value
        item.completed_at = timezone.now() if status_value == "completed" else None
        item.save(update_fields=["status", "completed_at", "updated_at"])
        if previous != status_value:
            LeadActivity.objects.create(
                lead=item.lead, event="follow_up_completed" if status_value == "completed" else "updated",
                title="Follow-up Completed" if status_value == "completed" else "Follow-up Updated",
                description=f"{item.get_follow_up_type_display()} · {item.get_status_display()}", actor=_user(request),
                metadata={"follow_up_id": item.id, "status": status_value},
            )
        messages.success(request, "Follow-up updated.")
    return redirect(request.POST.get("next") or "lead-follow-ups-page")


@require_POST
def bulk_lead_action(request):
    ids = [value for value in request.POST.getlist("lead_ids") if str(value).isdigit()]
    leads = Lead.objects.filter(id__in=ids, is_deleted=False)
    action = request.POST.get("bulk_action")
    if not ids:
        messages.error(request, "Select at least one lead.")
        return redirect("lead-list-page")
    if action == "delete":
        leads.update(is_deleted=True, updated_by=_user(request), updated_at=timezone.now())
    elif action == "status":
        value = request.POST.get("bulk_value", "")
        if value in {Lead.STATUS_CONVERTED, Lead.STATUS_LOST}:
            messages.error(request, "Convert or mark leads lost individually to capture required details.")
            return redirect("lead-list-page")
        for lead in leads:
            change_status(lead, value, request)
    elif action == "priority" and request.POST.get("bulk_value") in _choice_values(Lead.PRIORITY_CHOICES):
        for lead in leads:
            lead.priority = request.POST["bulk_value"]
            lead.updated_by = _user(request)
            lead.save(update_fields=["priority", "updated_by", "updated_at"])
            LeadActivity.objects.create(lead=lead, event="updated", title="Lead Updated", description=f"Priority changed to {lead.get_priority_display()}", actor=_user(request))
    elif action == "assign":
        assignee = User.objects.filter(pk=request.POST.get("bulk_value"), is_active=True).first()
        for lead in leads:
            lead.assigned_to = assignee
            lead.updated_by = _user(request)
            lead.save(update_fields=["assigned_to", "updated_by", "updated_at"])
            name = assignee.get_full_name() or assignee.username if assignee else "Unassigned"
            LeadActivity.objects.create(lead=lead, event="assigned", title="Assigned to Employee", description=f"Assigned to {name}", actor=_user(request), metadata={"assigned_to_id": assignee.id if assignee else None})
    elif action == "export":
        return export_leads(request, leads)
    else:
        messages.error(request, "Select a valid bulk action and value.")
        return redirect("lead-list-page")
    messages.success(request, f"{leads.count()} lead(s) updated.")
    return redirect("lead-list-page")


def export_leads(request, queryset=None):
    queryset = queryset if queryset is not None else filtered_leads(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="leads-{timezone.localdate().isoformat()}.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "Lead ID", "Shipping Name", "Country Code", "Phone", "Shipping Phone",
        "Email", "Shipping Address1", "Shipping Address2", "Shipping City",
        "Shipping Zip", "Shipping Province", "Shipping Province Name",
        "Shipping Country", "Products", "Status", "Created Date",
    ])
    for lead in queryset.select_related("assigned_to"):
        writer.writerow([
            lead.lead_id, lead.shipping_name or lead.full_name, lead.country_code,
            lead.phone, lead.shipping_phone, lead.email, lead.shipping_address1,
            lead.shipping_address2, lead.shipping_city, lead.shipping_zip,
            lead.shipping_province, lead.shipping_province_name,
            lead.shipping_country, "; ".join(product.name for product in lead.products.all()),
            lead.get_status_display(), timezone.localtime(lead.created_at).strftime("%Y-%m-%d %H:%M"),
        ])
    return response


def _base_context(request):
    page_params = request.GET.copy()
    page_params.pop("page", None)
    sort_params = page_params.copy()
    sort_params.pop("sort", None)
    return {
        "users": User.objects.filter(is_active=True).order_by("first_name", "username"),
        "status_choices": Lead.STATUS_CHOICES, "priority_choices": Lead.PRIORITY_CHOICES,
        "source_choices": Lead.SOURCE_CHOICES, "lost_reason_choices": Lead.LOST_REASON_CHOICES,
        "follow_up_type_choices": LeadFollowUp.TYPE_CHOICES,
        "payment_status_choices": LeadConversion.PAYMENT_STATUS_CHOICES,
        "country_dial_codes": COUNTRY_DIAL_CODES,
        "query": request.GET, "page_query": page_params.urlencode(),
        "sort_query": sort_params.urlencode(),
    }
