from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from store_app.models import UserActivityLog


class UserActivityAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="app-user", password="secret")
        self.other_user = User.objects.create_user(username="other-user", password="secret")
        self.client.force_authenticate(self.user)

    def test_user_can_only_read_own_logs(self):
        UserActivityLog.objects.create(user=self.user, event="own_event")
        UserActivityLog.objects.create(user=self.other_user, event="other_event")

        response = self.client.get("/api/app/activity/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["event"], "own_event")

    def test_non_admin_cannot_read_all_logs(self):
        response = self.client.get("/api/app/activity/all/")
        self.assertEqual(response.status_code, 403)

    def test_activity_endpoint_is_read_only(self):
        response = self.client.post("/api/app/activity/", {}, format="json")
        self.assertEqual(response.status_code, 405)
