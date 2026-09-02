import json

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from . import lead_management
from .access_control import ModuleAccessMiddleware, action_for_request
from .models import Lead, LeadConversion, LeadFollowUp, LeadStatusHistory, UserAccessProfile


class LeadManagementTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user("sales", password="test", first_name="Sales")

    def request(self, path, data):
        request = self.factory.post(path, json.dumps(data), content_type="application/json")
        request.user = self.user
        return request

    def create_lead(self):
        response = lead_management.LeadListCreateAPI.as_view()(self.request("/api/leads/", {
            "full_name": "Asha Patel", "phone": "9999999999",
            "email": "asha@example.com", "company_name": "A Co",
            "source": "website", "priority": "hot", "status": "new",
            "assigned_to": self.user.id,
        }))
        self.assertEqual(response.status_code, 201)
        return Lead.objects.get()

    def test_create_status_follow_up_and_convert_preserve_history(self):
        lead = self.create_lead()
        self.assertTrue(lead.activities.filter(event="created").exists())

        response = lead_management.LeadActionAPI.as_view()(
            self.request(f"/api/leads/{lead.id}/follow-up/", {
                "follow_up_date": "2026-09-03", "follow_up_time": "11:30",
                "follow_up_type": "call", "notes": "Discuss requirement",
            }), pk=lead.id, action="follow-up",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(LeadFollowUp.objects.filter(lead=lead).count(), 1)

        response = lead_management.LeadActionAPI.as_view()(
            self.request(f"/api/leads/{lead.id}/status/", {"status": "contacted"}),
            pk=lead.id, action="status",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(LeadStatusHistory.objects.filter(lead=lead, new_status="contacted").exists())

        response = lead_management.LeadActionAPI.as_view()(
            self.request(f"/api/leads/{lead.id}/convert/", {
                "conversion_date": "2026-09-05", "product_service": "Inventory Setup",
                "deal_amount": "125000", "payment_status": "partial", "notes": "PO received",
            }), pk=lead.id, action="convert",
        )
        self.assertEqual(response.status_code, 201)
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.STATUS_CONVERTED)
        self.assertTrue(LeadConversion.objects.filter(lead=lead).exists())
        self.assertTrue(lead.activities.filter(event="converted").exists())

    def test_mark_lost_requires_and_stores_reason(self):
        lead = self.create_lead()
        missing = lead_management.LeadActionAPI.as_view()(
            self.request(f"/api/leads/{lead.id}/mark-lost/", {}), pk=lead.id, action="mark-lost",
        )
        self.assertEqual(missing.status_code, 400)

        response = lead_management.LeadActionAPI.as_view()(
            self.request(f"/api/leads/{lead.id}/mark-lost/", {
                "lost_reason": "budget_issue", "notes": "Revisit next quarter",
            }), pk=lead.id, action="mark-lost",
        )
        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.STATUS_LOST)
        self.assertEqual(lead.lost_reason, "budget_issue")
        self.assertIsNotNone(lead.lost_at)

    def test_soft_delete_keeps_related_history(self):
        lead = self.create_lead()
        request = self.factory.delete(f"/api/leads/{lead.id}/")
        request.user = self.user
        response = lead_management.LeadDetailAPI.as_view()(request, pk=lead.id)
        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertTrue(lead.is_deleted)
        self.assertTrue(lead.activities.exists())

    def test_module_actions_map_to_existing_role_permissions(self):
        self.assertEqual(action_for_request(self.factory.post("/api/leads-page/add/")), "add")
        self.assertEqual(action_for_request(self.factory.post("/api/leads-page/1/edit/")), "edit")
        self.assertEqual(action_for_request(self.factory.post("/api/leads-page/1/status/")), "edit")
        self.assertEqual(action_for_request(self.factory.post("/api/leads-page/1/delete/")), "delete")
        bulk_delete = self.factory.post(
            "/api/leads/bulk/", json.dumps({"lead_ids": [1], "action": "delete"}),
            content_type="application/json",
        )
        self.assertEqual(action_for_request(bulk_delete), "delete")

    def test_reference_stats_related_and_bulk_apis(self):
        lead = self.create_lead()
        for view in (lead_management.LeadOptionsAPI, lead_management.LeadStatsAPI):
            request = self.factory.get("/api/leads/reference/")
            request.user = self.user
            self.assertEqual(view.as_view()(request).status_code, 200)

        request = self.factory.get(f"/api/leads/{lead.id}/activities/")
        request.user = self.user
        response = lead_management.LeadRelatedAPI.as_view()(request, pk=lead.id, resource="activities")
        self.assertEqual(response.status_code, 200)

        response = lead_management.LeadBulkAPI.as_view()(
            self.request("/api/leads/bulk/", {
                "lead_ids": [lead.id], "action": "priority", "value": "cold",
            })
        )
        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.priority, "cold")

    def test_module_middleware_allows_only_selected_lead_actions(self):
        profile = UserAccessProfile.objects.create(
            user=self.user, role=UserAccessProfile.ROLE_USER,
            modules=["leads"], action_permissions={"leads": ["view"]},
        )
        middleware = ModuleAccessMiddleware(lambda request: HttpResponse("allowed"))

        view_request = self.factory.get("/api/leads/")
        view_request.user = self.user
        self.assertEqual(middleware(view_request).status_code, 200)

        add_request = self.factory.post(
            "/api/leads/", json.dumps({"full_name": "No Access"}),
            content_type="application/json",
        )
        add_request.user = self.user
        self.assertEqual(middleware(add_request).status_code, 403)

        profile.modules = []
        profile.action_permissions = {}
        profile.save(update_fields=["modules", "action_permissions"])
        denied_request = self.factory.get("/api/leads/")
        denied_request.user = self.user
        self.assertEqual(middleware(denied_request).status_code, 403)
