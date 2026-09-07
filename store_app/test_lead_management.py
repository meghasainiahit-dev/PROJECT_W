import csv
import io
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from . import lead_management
from .access_control import ModuleAccessMiddleware, action_for_request
from .models import (
    Inventory, Lead, LeadConversion, LeadFollowUp, LeadStatusHistory, Product,
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

    def test_shopify_checkout_csv_import_groups_items_and_skips_duplicates(self):
        vendor = Vendor.objects.create(
            name="Import Vendor", mobile="9000000000", city="Mumbai",
            state="Maharashtra", country="India", pin_code="400001",
        )
        first = Product.objects.create(vendor=vendor, name="Imported Product One", prefix_code="I1")
        second = Product.objects.create(vendor=vendor, name="Imported Product Two", prefix_code="I2")
        columns = [
            "Name", "Id", "Email", "Phone", "Shipping Phone", "Shipping Name",
            "Shipping Address1", "Shipping Address2", "Shipping City", "Shipping Zip",
            "Shipping Province", "Shipping Province Name", "Shipping Country",
            "Lineitem quantity", "Lineitem name", "Lineitem sku", "Note Attributes",
        ]
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerow({
            "Name": "#CHECKOUT-1", "Id": "CHECKOUT-1", "Email": "buyer@example.com",
            "Phone": "+919876500000", "Shipping Phone": "09876500001",
            "Shipping Name": "Buyer Name", "Shipping Address1": "MG Road",
            "Shipping Address2": "Near Metro", "Shipping City": "Mumbai",
            "Shipping Zip": "'400001", "Shipping Province": "MH",
            "Shipping Province Name": "Maharashtra", "Shipping Country": "IN",
            "Lineitem quantity": "1", "Lineitem name": first.name, "Lineitem sku": first.sku,
        })
        writer.writerow({
            "Name": "#CHECKOUT-1", "Email": "buyer@example.com",
            "Lineitem quantity": "2", "Lineitem name": second.name, "Lineitem sku": second.sku,
        })
        writer.writerow({
            "Name": "#CHECKOUT-1", "Email": "buyer@example.com",
            "Lineitem quantity": "1", "Lineitem name": "New CSV Product", "Lineitem sku": "CSV-NEW-1",
        })
        csv_bytes = stream.getvalue().encode()

        result = lead_management.import_leads_csv(
            SimpleUploadedFile("checkouts.csv", csv_bytes, content_type="text/csv"), self.user,
        )
        self.assertEqual(result["source_rows"], 3)
        self.assertEqual(result["checkout_groups"], 1)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["products_created"], 1)
        self.assertEqual(result["product_links"], 3)
        imported_product = Product.objects.get(sku="CSV-NEW-1")
        self.assertTrue(Inventory.objects.filter(product=imported_product).exists())
        lead = Lead.objects.get(external_checkout_id="CHECKOUT-1")
        self.assertEqual(lead.country_code, "+91")
        self.assertEqual(lead.phone, "9876500000")
        self.assertEqual(lead.shipping_phone, "9876500001")
        self.assertEqual(lead.shipping_country, "India")
        self.assertEqual(lead.shipping_zip, "400001")
        self.assertEqual(
            set(lead.products.values_list("id", flat=True)),
            {first.id, second.id, imported_product.id},
        )

        duplicate = lead_management.import_leads_csv(
            SimpleUploadedFile("checkouts.csv", csv_bytes, content_type="text/csv"), self.user,
        )
        self.assertEqual(duplicate["created"], 0)
        self.assertEqual(duplicate["duplicates_skipped"], 1)
        self.assertEqual(Lead.objects.count(), 1)

        page_request = self.factory.get("/api/leads-page/import/")
        page_request.user = self.user
        page = lead_management.lead_import_page(page_request)
        self.assertContains(page, "Bulk Upload Leads")
        self.assertContains(page, 'name="file"')

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
        self.assertEqual(action_for_request(self.factory.post("/api/leads-page/import/")), "add")
        self.assertEqual(action_for_request(self.factory.post("/api/leads/import/")), "add")
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

    def test_complete_app_api_flow_with_bearer_token(self):
        app_user = User.objects.create_superuser(
            "app-admin", "app-admin@example.com", "AppPass123!",
        )
        vendor = Vendor.objects.create(
            name="App Vendor", mobile="9000000000", city="Mumbai",
            state="Maharashtra", country="India", pin_code="400001",
        )
        product = Product.objects.create(
            vendor=vendor, name="App Product", sku="APP-PRODUCT-1",
            barcode="APP-PRODUCT-1", retailer_price="125.00",
        )
        client = Client(HTTP_HOST="127.0.0.1:8000")

        self.assertEqual(client.get("/api/leads/").status_code, 401)
        login = client.post(
            "/api/app/login/",
            data=json.dumps({"username": app_user.username, "password": "AppPass123!"}),
            content_type="application/json",
        )
        self.assertEqual(login.status_code, 200)
        token = login.json()["token"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        def request(method, path, payload=None):
            kwargs = dict(auth)
            if payload is not None:
                kwargs.update(data=json.dumps(payload), content_type="application/json")
            return getattr(client, method.lower())(path, **kwargs)

        for path in ("/api/leads/options/", "/api/leads/stats/", "/api/leads/"):
            self.assertEqual(request("GET", path).status_code, 200, path)

        create_payload = {
            "shipping_name": "App API Lead", "country_code": "+91",
            "phone": "9876543210", "shipping_phone": "9876543211",
            "email": "app-lead@example.com", "shipping_address1": "MG Road",
            "shipping_city": "Mumbai", "shipping_zip": "400001",
            "shipping_province": "MH", "shipping_province_name": "Maharashtra",
            "shipping_country": "India", "product_ids": [product.id],
        }
        created = request("POST", "/api/leads/", create_payload)
        self.assertEqual(created.status_code, 201)
        lead_id = created.json()["id"]
        self.assertEqual(created.json()["products"][0]["id"], product.id)
        self.assertEqual(request("GET", f"/api/leads/{lead_id}/").status_code, 200)

        patched = request("PATCH", f"/api/leads/{lead_id}/", {"shipping_city": "Pune"})
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["shipping_city"], "Pune")
        put_payload = {**create_payload, "shipping_name": "App API Lead Updated", "status": "contacted"}
        self.assertEqual(request("PUT", f"/api/leads/{lead_id}/", put_payload).status_code, 200)
        self.assertEqual(request(
            "POST", f"/api/leads/{lead_id}/status/",
            {"status": "qualified", "reason": "API verification"},
        ).status_code, 200)

        note = request(
            "POST", f"/api/leads/{lead_id}/note/", {"note": "Created from app API test."},
        )
        self.assertEqual(note.status_code, 201)
        follow_up_date = (timezone.localdate() + timedelta(days=3)).isoformat()
        follow_up = request("POST", f"/api/leads/{lead_id}/follow-up/", {
            "follow_up_date": follow_up_date, "follow_up_time": "15:30",
            "follow_up_type": "call", "notes": "API follow-up",
            "assigned_to": app_user.id,
        })
        self.assertEqual(follow_up.status_code, 201)
        follow_up_id = follow_up.json()["id"]

        for path in (
            f"/api/leads/{lead_id}/activities/",
            f"/api/leads/{lead_id}/follow-ups/",
            f"/api/leads/{lead_id}/notes/",
            f"/api/leads/{lead_id}/status-history/",
            f"/api/leads/follow-ups/?lead={lead_id}",
            f"/api/leads/follow-ups/{follow_up_id}/",
        ):
            self.assertEqual(request("GET", path).status_code, 200, path)

        updated_follow_up = request(
            "PATCH", f"/api/leads/follow-ups/{follow_up_id}/", {"status": "completed"},
        )
        self.assertEqual(updated_follow_up.status_code, 200)
        self.assertEqual(updated_follow_up.json()["status"], "completed")
        self.assertEqual(request("PUT", f"/api/leads/follow-ups/{follow_up_id}/", {
            "follow_up_date": follow_up_date, "follow_up_time": "16:00",
            "follow_up_type": "meeting", "status": "completed",
            "notes": "Fully updated", "assigned_to": app_user.id,
        }).status_code, 200)

        second = request("POST", "/api/leads/", {
            "shipping_name": "App Lost Lead", "phone": "9123456780",
            "shipping_country": "India",
        })
        self.assertEqual(second.status_code, 201)
        second_id = second.json()["id"]
        for action, value in (("priority", "hot"), ("assign", app_user.id)):
            response = request("POST", "/api/leads/bulk/", {
                "lead_ids": [lead_id, second_id], "action": action, "value": value,
            })
            self.assertEqual(response.status_code, 200)
        self.assertEqual(request("POST", "/api/leads/bulk/", {
            "lead_ids": [second_id], "action": "status", "value": "negotiation",
        }).status_code, 200)

        self.assertEqual(request("POST", f"/api/leads/{lead_id}/convert/", {
            "conversion_date": timezone.localdate().isoformat(),
            "product_service": "App Product", "deal_amount": "1250.00",
            "payment_status": "paid", "notes": "Converted through API",
        }).status_code, 201)
        lost = request("POST", f"/api/leads/{second_id}/mark-lost/", {
            "lost_reason": "budget_issue", "notes": "API lost flow",
        })
        self.assertEqual(lost.status_code, 200)
        self.assertEqual(lost.json()["lost_reason"], "budget_issue")

        csv_columns = [
            "Name", "Id", "Email", "Phone", "Shipping Name", "Shipping Address1",
            "Shipping City", "Shipping Country", "Lineitem quantity",
            "Lineitem name", "Lineitem price", "Lineitem sku",
        ]
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=csv_columns)
        writer.writeheader()
        writer.writerow({
            "Name": "#APP-IMPORT-1", "Id": "APP-IMPORT-1",
            "Email": "import@example.com", "Phone": "+919999999999",
            "Shipping Name": "Imported App Lead", "Shipping Address1": "CSV Road",
            "Shipping City": "Delhi", "Shipping Country": "IN",
            "Lineitem quantity": "1", "Lineitem name": "CSV App Product",
            "Lineitem price": "299.00", "Lineitem sku": "CSV-APP-1",
        })
        csv_bytes = stream.getvalue().encode("utf-8")
        imported = client.post(
            "/api/leads/import/",
            {"file": SimpleUploadedFile("app-import.csv", csv_bytes, content_type="text/csv")},
            **auth,
        )
        self.assertEqual(imported.status_code, 201)
        self.assertEqual(imported.json()["created"], 1)
        self.assertEqual(imported.json()["products_created"], 1)
        duplicate = client.post(
            "/api/leads/import/",
            {"file": SimpleUploadedFile("app-import.csv", csv_bytes, content_type="text/csv")},
            **auth,
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json()["duplicates_skipped"], 1)

        exported = request("GET", "/api/leads/export/?view=all")
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported["Content-Type"].startswith("text/csv"))
        self.assertEqual(request("DELETE", f"/api/leads/follow-ups/{follow_up_id}/").status_code, 200)
        self.assertEqual(request("POST", "/api/leads/bulk/", {
            "lead_ids": [second_id], "action": "delete",
        }).status_code, 200)
        self.assertEqual(request("DELETE", f"/api/leads/{lead_id}/").status_code, 200)
