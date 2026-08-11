from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from invites.models import Invite
from news.models import News
from partner_programs.models import Application
from projects.models import Collaborator, Project
from projects.tests.helpers import (
    create_collaborator,
    create_partner_program,
    create_project,
    create_staff_user,
    create_user,
)
from projects.workspace_selectors import get_subscribed_projects_queryset
from projects.workspace_serializers import ProjectWorkspaceListSerializer


class SubscribedProjectsAPITests(TestCase):
    url = "/projects/subscribed/"

    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="subscribed-projects-user")
        self.other_user = create_user(prefix="subscribed-projects-other")
        self.leader = create_user(prefix="subscribed-projects-leader")

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.user)

    def subscribe(self, project, user=None):
        project.subscribers.add(user or self.user)

    def create_public_project(self, **kwargs):
        return create_project(
            leader=kwargs.pop("leader", self.leader),
            draft=False,
            is_public=True,
            **kwargs,
        )

    def response_ids(self, response):
        return [item["id"] for item in response.data["results"]]

    def test_endpoint_requires_authentication(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)

    def test_user_without_subscriptions_gets_empty_paginated_response(self):
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"count": 0, "next": None, "previous": None, "results": []},
        )

    def test_only_current_users_public_subscriptions_are_returned(self):
        subscribed = self.create_public_project(name="Current subscription")
        other_subscription = self.create_public_project(name="Other subscription")
        self.subscribe(subscribed)
        self.subscribe(other_subscription, self.other_user)
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.response_ids(response), [subscribed.pk])

    def test_multiple_subscriptions_are_unique(self):
        first = self.create_public_project(name="First subscription")
        second = self.create_public_project(name="Second subscription")
        self.subscribe(first)
        self.subscribe(first)
        self.subscribe(second)
        for project in (first, second):
            for index in range(2):
                Application.objects.create(
                    program=create_partner_program(name=f"Program {project.pk}-{index}"),
                    user=self.user,
                    created_by=self.user,
                    project=project,
                )
        self.authenticate()

        response = self.client.get(self.url)
        ids = self.response_ids(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(ids), {first.pk, second.pk})
        self.assertEqual(len(ids), 2)

    def test_workspace_subscribe_adds_and_unsubscribe_removes_project(self):
        project = self.create_public_project()
        self.authenticate()

        subscribed = self.client.post(
            f"/projects/{project.pk}/workspace/subscription/",
            {},
            format="json",
        )
        after_subscribe = self.client.get(self.url)
        unsubscribed = self.client.delete(
            f"/projects/{project.pk}/workspace/subscription/",
            {},
            format="json",
        )
        after_unsubscribe = self.client.get(self.url)

        self.assertEqual(subscribed.status_code, 200)
        self.assertEqual(self.response_ids(after_subscribe), [project.pk])
        self.assertEqual(unsubscribed.status_code, 200)
        self.assertEqual(self.response_ids(after_unsubscribe), [])

    def test_foreign_private_and_draft_subscriptions_are_hidden(self):
        hidden_projects = (
            create_project(
                leader=self.leader,
                name="Private project",
                draft=False,
                is_public=False,
            ),
            create_project(
                leader=self.leader,
                name="Draft project",
                draft=True,
                is_public=True,
            ),
        )
        for project in hidden_projects:
            self.subscribe(project)
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.response_ids(response), [])

    def test_leader_sees_subscribed_private_and_draft_projects(self):
        projects = (
            create_project(
                leader=self.user,
                draft=False,
                is_public=False,
            ),
            create_project(
                leader=self.user,
                draft=True,
                is_public=True,
            ),
        )
        for project in projects:
            self.subscribe(project)
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(set(self.response_ids(response)), {item.pk for item in projects})

    def test_collaborator_sees_subscribed_private_and_draft_projects(self):
        projects = (
            create_project(
                leader=self.leader,
                draft=False,
                is_public=False,
            ),
            create_project(
                leader=self.leader,
                draft=True,
                is_public=True,
            ),
        )
        for project in projects:
            create_collaborator(project, user=self.user)
            self.subscribe(project)
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(set(self.response_ids(response)), {item.pk for item in projects})
        self.assertTrue(
            all(
                item["current_user_role"] == "collaborator"
                for item in response.data["results"]
            )
        )

    def test_staff_and_superuser_see_their_private_subscriptions(self):
        private_project = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )
        staff = create_user(prefix="subscribed-projects-staff")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        superuser = create_staff_user(prefix="subscribed-projects-superuser")

        for admin_user in (staff, superuser):
            with self.subTest(user=admin_user.email):
                self.subscribe(private_project, admin_user)
                self.authenticate(admin_user)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.response_ids(response), [private_project.pk])

    def test_lost_access_hides_project_without_removing_subscription(self):
        project = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )
        collaboration = create_collaborator(project, user=self.user)
        self.subscribe(project)
        self.authenticate()
        self.assertEqual(self.response_ids(self.client.get(self.url)), [project.pk])

        collaboration.delete()
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.response_ids(response), [])
        self.assertTrue(project.subscribers.filter(pk=self.user.pk).exists())

    def test_search_is_trimmed_case_insensitive_and_subscription_scoped(self):
        match = self.create_public_project(name="Solar Laboratory")
        non_match = self.create_public_project(name="Marine Laboratory")
        foreign_match = self.create_public_project(name="Solar Foreign")
        self.subscribe(match)
        self.subscribe(non_match)
        self.subscribe(foreign_match, self.other_user)
        self.authenticate()

        response = self.client.get(self.url, {"search": "  sOLAR labORATORY  "})
        empty_search = self.client.get(self.url, {"search": "   "})

        self.assertEqual(self.response_ids(response), [match.pk])
        self.assertEqual(
            set(self.response_ids(empty_search)),
            {match.pk, non_match.pk},
        )

    def test_page_pagination_uses_existing_shape_and_size(self):
        projects = [
            self.create_public_project(name=f"Paginated {index}") for index in range(11)
        ]
        for project in projects:
            self.subscribe(project)
        self.authenticate()

        first_page = self.client.get(self.url, {"page": 1})
        second_page = self.client.get(self.url, {"page": 2})
        missing_page = self.client.get(self.url, {"page": 99})

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(set(first_page.data), {"count", "next", "previous", "results"})
        self.assertEqual(first_page.data["count"], 11)
        self.assertEqual(len(first_page.data["results"]), 10)
        self.assertIn("page=2", first_page.data["next"])
        self.assertIsNone(first_page.data["previous"])
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.data["results"]), 1)
        self.assertIsNotNone(second_page.data["previous"])
        self.assertIsNone(second_page.data["next"])
        self.assertEqual(missing_page.status_code, 404)

    def test_invalid_page_returns_safe_not_found(self):
        self.authenticate()

        for page in ("invalid", "0", "-1"):
            with self.subTest(page=page):
                response = self.client.get(self.url, {"page": page})
                self.assertEqual(response.status_code, 404)
                self.assertEqual(set(response.data), {"detail"})

    def test_projects_are_ordered_by_update_time_and_stable_id(self):
        older = self.create_public_project(name="Older")
        first_same_time = self.create_public_project(name="Same time first")
        second_same_time = self.create_public_project(name="Same time second")
        now = timezone.now()
        Project.objects.filter(pk=older.pk).update(
            datetime_updated=now - timedelta(days=1)
        )
        Project.objects.filter(pk__in=(first_same_time.pk, second_same_time.pk)).update(
            datetime_updated=now
        )
        for project in (older, first_same_time, second_same_time):
            self.subscribe(project)
        self.authenticate()

        response = self.client.get(self.url)

        self.assertEqual(
            self.response_ids(response),
            [second_same_time.pk, first_same_time.pk, older.pk],
        )

    def test_card_contract_has_no_subscriber_or_personal_data(self):
        project = self.create_public_project()
        self.subscribe(project)
        self.authenticate()

        response = self.client.get(self.url)
        card = response.data["results"][0]

        self.assertEqual(
            set(card),
            {
                "id",
                "name",
                "short_description",
                "image_address",
                "cover_image_address",
                "draft",
                "is_public",
                "current_user_role",
                "can_edit",
                "can_use_in_application",
                "activities",
                "datetime_updated",
            },
        )
        for forbidden in (
            "subscribers",
            "email",
            "phone_number",
            "birthday",
            "invitations",
        ):
            self.assertNotIn(forbidden, card)

    def test_get_does_not_change_domain_objects(self):
        project = self.create_public_project()
        self.subscribe(project)
        Invite.objects.create(
            project=project,
            user=self.user,
            invited_by=self.leader,
        )
        News.objects.create(content_object=project, text="Existing project news")
        before = {
            "projects": Project.objects.count(),
            "subscriptions": Project.subscribers.through.objects.count(),
            "collaborators": Collaborator.objects.count(),
            "invites": Invite.objects.count(),
            "news": News.objects.count(),
        }
        updated_at = project.datetime_updated
        self.authenticate()

        response = self.client.get(self.url)
        project.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {
                "projects": Project.objects.count(),
                "subscriptions": Project.subscribers.through.objects.count(),
                "collaborators": Collaborator.objects.count(),
                "invites": Invite.objects.count(),
                "news": News.objects.count(),
            },
            before,
        )
        self.assertEqual(project.datetime_updated, updated_at)

    def test_serializer_uses_only_prefetched_data(self):
        projects = [self.create_public_project() for _index in range(3)]
        for project in projects:
            self.subscribe(project)
            Application.objects.create(
                program=create_partner_program(),
                user=self.user,
                created_by=self.user,
                project=project,
            )
        prepared_projects = list(get_subscribed_projects_queryset(user=self.user))
        request = APIRequestFactory().get(self.url)
        request.user = self.user

        with self.assertNumQueries(0):
            data = ProjectWorkspaceListSerializer(
                prepared_projects,
                many=True,
                context={"request": request},
            ).data

        self.assertEqual(len(data), 3)
        self.assertTrue(all(item["activities"] for item in data))

    def test_endpoint_query_budget_does_not_grow_with_project_count(self):
        projects = [self.create_public_project() for _index in range(5)]
        for project in projects:
            self.subscribe(project)
            Application.objects.create(
                program=create_partner_program(),
                user=self.user,
                created_by=self.user,
                project=project,
            )
        self.authenticate()

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url, {"page": 1})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 5)
        self.assertLessEqual(len(queries), 5)
