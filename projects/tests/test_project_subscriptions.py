from django.test import TestCase
from rest_framework.test import APIClient

from .helpers import create_project, create_user


class ProjectSubscriptionRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.project = create_project(draft=False, is_public=True)
        self.user = create_user(prefix="project-subscriber")
        self.client.force_authenticate(self.user)

    def test_user_can_subscribe_to_public_project(self):
        response = self.client.post(f"/projects/{self.project.id}/subscribe/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.project.subscribers.filter(pk=self.user.id).exists())

    def test_user_can_unsubscribe_from_project(self):
        self.project.subscribers.add(self.user)

        response = self.client.post(f"/projects/{self.project.id}/unsubscribe/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.project.subscribers.filter(pk=self.user.id).exists())

    def test_subscribers_list_returns_project_subscribers(self):
        subscriber = create_user(prefix="project-subscriber-list")
        self.project.subscribers.add(subscriber)

        response = self.client.get(f"/projects/{self.project.id}/subscribers/")

        self.assertEqual(response.status_code, 200)
        subscriber_ids = [item["id"] for item in response.data]
        self.assertIn(subscriber.id, subscriber_ids)
