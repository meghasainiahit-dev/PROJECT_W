import json

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from . import lead_management
from .access_control import action_for_request
from .models import Lead, LeadConversion, LeadFollowUp, LeadStatusHistory


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
