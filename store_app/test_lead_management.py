import json

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from . import lead_management
from .access_control import ModuleAccessMiddleware, action_for_request
from .models import (
    Lead, LeadConversion, LeadFollowUp, LeadStatusHistory, Product,
    UserAccessProfile, Vendor,
)


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

    def test_shipping_customer_fields_country_code_and_multiple_products(self):
        vendor = Vendor.objects.create(
            name="Demo Vendor", mobile="9000000000", city="Mumbai",
            state="Maharashtra", country="India", pin_code="400001",
        )
        first = Product.objects.create(vendor=vendor, name="Product One", prefix_code="P1")
        second = Product.objects.create(vendor=vendor, name="Product Two", prefix_code="P2")
        response = lead_management.LeadListCreateAPI.as_view()(self.request("/api/leads/", {
            "shipping_name": "Riya Sharma", "country_code": "+91",
            "phone": "9876500000", "shipping_phone": "9876500001",
            "email": "riya@example.com", "shipping_address1": "MG Road",
            "shipping_address2": "Near Metro", "shipping_city": "Mumbai",
            "shipping_zip": "400001", "shipping_province": "MH",
            "shipping_province_name": "Maharashtra", "shipping_country": "India",
            "product_ids": [first.id, second.id],
        }))
        self.assertEqual(response.status_code, 201)
        lead = Lead.objects.get()
        self.assertEqual(lead.full_name, "Riya Sharma")
        self.assertEqual(lead.shipping_name, "Riya Sharma")
        self.assertEqual(lead.country_code, "+91")
        self.assertEqual(lead.products.count(), 2)
        payload = json.loads(response.content)
        self.assertEqual({row["id"] for row in payload["products"]}, {first.id, second.id})

        page_request = self.factory.get("/api/leads-page/add/")
        page_request.user = self.user
        page = lead_management.lead_form_page(page_request)
        html = page.content.decode()
        for field_name in (
            "shipping_name", "country_code", "phone", "shipping_phone", "email",
            "shipping_address1", "shipping_address2", "shipping_city", "shipping_zip",
            "shipping_province", "shipping_province_name", "shipping_country", "product_ids",
        ):
            self.assertIn(f'name="{field_name}"', html)
        self.assertIn("Product One", html)
        self.assertIn("Product Two", html)
        self.assertNotIn('name="company_name"', html)
        self.assertNotIn('name="source"', html)

        search_request = self.factory.get("/api/leads/?search=Product%20One")
        search_request.user = self.user
        search_response = lead_management.LeadListCreateAPI.as_view()(search_request)
        self.assertEqual(search_response.status_code, 200)
        self.assertEqual(json.loads(search_response.content)["count"], 1)

        export_request = self.factory.get("/api/leads/export/")
        export_request.user = self.user
        export_response = lead_management.export_leads(export_request)
        exported = export_response.content.decode()
        self.assertIn("Shipping Name,Country Code,Phone,Shipping Phone", exported)
        self.assertIn("Product One; Product Two", exported)

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
