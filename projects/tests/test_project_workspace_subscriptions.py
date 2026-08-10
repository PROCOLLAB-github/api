from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from invites.models import Invite
from news.models import News
from projects.models import Collaborator
from projects.tests.helpers import (
    create_collaborator,
    create_project,
    create_staff_user,
    create_user,
)
from projects.workspace_selectors import get_workspace_subscription_queryset
from projects.workspace_serializers import ProjectSubscriptionStateSerializer


class ProjectWorkspaceSubscriptionAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.leader = create_user(prefix="subscription-leader")
        self.collaborator = create_user(prefix="subscription-collaborator")
        self.outsider = create_user(prefix="subscription-outsider")
        self.staff = create_user(prefix="subscription-staff")
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])
        self.superuser = create_staff_user(prefix="subscription-superuser")
        self.public_project = create_project(
            leader=self.leader,
            draft=False,
            is_public=True,
        )
        self.private_project = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def url(self, project=None):
        project = project or self.public_project
        return f"/projects/{project.pk}/workspace/subscription/"

    def test_all_methods_require_authentication(self):
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.assertEqual(
            self.client.post(self.url(), {}, format="json").status_code,
            401,
        )
        self.assertEqual(
            self.client.delete(self.url(), {}, format="json").status_code,
            401,
        )

    def test_get_returns_unsubscribed_state_for_current_user(self):
        self.public_project.subscribers.add(self.leader)
        self.authenticate(self.outsider)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"is_subscribed": False, "subscribers_count": 1},
        )

    def test_subscribe_is_idempotent_and_updates_count(self):
        other_subscriber = create_user(prefix="subscription-other")
        self.public_project.subscribers.add(other_subscriber)
        self.authenticate(self.outsider)

        first = self.client.post(self.url(), {}, format="json")
        second = self.client.post(self.url(), {}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(
            first.data,
            {"is_subscribed": True, "subscribers_count": 2},
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data, first.data)
        self.assertEqual(
            self.public_project.subscribers.filter(pk=self.outsider.pk).count(),
            1,
        )

    def test_unsubscribe_is_idempotent_and_updates_count(self):
        self.public_project.subscribers.add(self.outsider, self.leader)
        self.authenticate(self.outsider)

        first = self.client.delete(self.url(), {}, format="json")
        second = self.client.delete(self.url(), {}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(
            first.data,
            {"is_subscribed": False, "subscribers_count": 1},
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data, first.data)
        self.assertFalse(
            self.public_project.subscribers.filter(pk=self.outsider.pk).exists()
        )

    def test_multiple_users_have_independent_state(self):
        second_user = create_user(prefix="subscription-second")
        self.public_project.subscribers.add(self.outsider)

        self.authenticate(self.outsider)
        subscribed = self.client.get(self.url())
        self.authenticate(second_user)
        unsubscribed = self.client.get(self.url())

        self.assertTrue(subscribed.data["is_subscribed"])
        self.assertFalse(unsubscribed.data["is_subscribed"])
        self.assertEqual(subscribed.data["subscribers_count"], 1)
        self.assertEqual(unsubscribed.data["subscribers_count"], 1)

    def test_workspace_detail_contains_annotated_subscription_state(self):
        other_subscriber = create_user(prefix="subscription-detail-other")
        self.public_project.subscribers.add(other_subscriber)
        self.authenticate(self.outsider)

        response = self.client.get(f"/projects/{self.public_project.pk}/workspace/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_subscribed"])
        self.assertEqual(response.data["subscribers_count"], 1)
        self.public_project.subscribers.add(self.outsider)
        response = self.client.get(f"/projects/{self.public_project.pk}/workspace/")
        self.assertTrue(response.data["is_subscribed"])
        self.assertEqual(response.data["subscribers_count"], 2)

    def test_private_project_is_visible_to_workspace_members_and_admins(self):
        create_collaborator(self.private_project, user=self.collaborator)

        for user in (self.leader, self.collaborator, self.staff, self.superuser):
            with self.subTest(user=user.email):
                self.authenticate(user)
                response = self.client.get(self.url(self.private_project))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.data,
                    {"is_subscribed": False, "subscribers_count": 0},
                )
                subscribed = self.client.post(
                    self.url(self.private_project),
                    {},
                    format="json",
                )
                self.assertEqual(subscribed.status_code, 200)
                self.assertTrue(subscribed.data["is_subscribed"])
                removed = self.client.delete(
                    self.url(self.private_project),
                    {},
                    format="json",
                )
                self.assertEqual(removed.status_code, 200)
                self.assertEqual(
                    removed.data,
                    {"is_subscribed": False, "subscribers_count": 0},
                )

    def test_private_project_is_hidden_from_outsider(self):
        self.authenticate(self.outsider)

        for method in ("get", "post", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url(self.private_project),
                    {},
                    format="json",
                )
                self.assertEqual(response.status_code, 404)

    def test_missing_project_returns_safe_not_found(self):
        self.authenticate(self.outsider)

        url = "/projects/999999999/workspace/subscription/"
        for method in ("get", "post", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(str(self.outsider.pk), str(response.data))
                self.assertNotIn("999999999", str(response.data))

    def test_invalid_action_payload_is_rejected_without_mutation(self):
        self.authenticate(self.outsider)

        post_response = self.client.post(
            self.url(), {"user_id": self.leader.pk}, format="json"
        )
        delete_response = self.client.delete(
            self.url(), {"project_id": self.public_project.pk}, format="json"
        )

        self.assertEqual(post_response.status_code, 400)
        self.assertEqual(delete_response.status_code, 400)
        self.assertFalse(
            self.public_project.subscribers.filter(pk=self.outsider.pk).exists()
        )

    def test_response_never_contains_subscriber_profiles(self):
        self.public_project.subscribers.add(self.leader)
        self.authenticate(self.outsider)

        response = self.client.get(self.url())
        detail = self.client.get(f"/projects/{self.public_project.pk}/workspace/")

        self.assertEqual(set(response.data), {"is_subscribed", "subscribers_count"})
        self.assertNotIn("subscribers", detail.data)
        self.assertNotIn(self.leader.email, str(response.data))
        self.assertNotIn(self.leader.email, str(detail.data))

    def test_subscription_does_not_create_related_domain_objects(self):
        self.authenticate(self.outsider)
        counts_before = {
            "collaborators": Collaborator.objects.count(),
            "invites": Invite.objects.count(),
            "news": News.objects.count(),
        }

        response = self.client.post(self.url(), {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Collaborator.objects.count(), counts_before["collaborators"])
        self.assertEqual(Invite.objects.count(), counts_before["invites"])
        self.assertEqual(News.objects.count(), counts_before["news"])

    def test_state_serializer_performs_no_database_queries(self):
        self.authenticate(self.outsider)
        project = get_workspace_subscription_queryset(user=self.outsider).get(
            pk=self.public_project.pk
        )

        with self.assertNumQueries(0):
            data = ProjectSubscriptionStateSerializer(project).data

        self.assertEqual(
            data,
            {"is_subscribed": False, "subscribers_count": 0},
        )

    def test_state_endpoint_query_budget_does_not_depend_on_subscriber_count(self):
        subscribers = [
            create_user(prefix=f"subscription-budget-{index}") for index in range(8)
        ]
        self.public_project.subscribers.add(*subscribers)
        self.authenticate(self.outsider)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["subscribers_count"], len(subscribers))
        self.assertLessEqual(len(queries), 2)
