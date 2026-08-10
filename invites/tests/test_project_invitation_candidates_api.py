from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from invites.models import Invite
from invites.tests.helpers import (
    add_collaborator,
    add_user_to_program,
    create_project,
    create_user,
    link_project_to_program,
)
from invites.throttling import ProjectInvitationCandidateSearchScopedRateThrottle
from projects.models import Collaborator


class ProjectInvitationCandidateAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.leader = self.create_named_user("candidate-leader", "Лидер", "Проекта")
        self.collaborator = self.create_named_user(
            "candidate-collaborator", "Участник", "Проекта"
        )
        self.outsider = self.create_named_user(
            "candidate-outsider", "Посторонний", "Пользователь"
        )
        self.staff = self.create_named_user(
            "candidate-staff", "Администратор", "Платформы", is_staff=True
        )
        self.superuser = self.create_named_user(
            "candidate-superuser", "Главный", "Администратор"
        )
        self.superuser.is_superuser = True
        self.superuser.save(update_fields=["is_superuser"])
        self.project = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )
        add_collaborator(project=self.project, user=self.collaborator)

    @staticmethod
    def create_named_user(
        prefix,
        first_name="Иван",
        last_name="Петров",
        *,
        is_staff=False,
        is_active=True,
    ):
        user = create_user(prefix=prefix, is_staff=is_staff)
        user.first_name = first_name
        user.last_name = last_name
        user.is_active = is_active
        user.save(update_fields=["first_name", "last_name", "is_active"])
        return user

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def candidates_url(self, project=None):
        project = project or self.project
        return f"/projects/{project.pk}/workspace/invitations/candidates/"

    def search(self, query="петров", *, project=None):
        return self.client.get(self.candidates_url(project), {"q": query})

    def test_endpoint_requires_authentication(self):
        response = self.search()

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_leader_staff_and_superuser_can_search(self):
        candidate = self.create_named_user("candidate-authorized", "Иван", "Петров")

        for actor in (self.leader, self.staff, self.superuser):
            with self.subTest(actor=actor.pk):
                self.authenticate(actor)
                response = self.search()
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(
                    [item["id"] for item in response.data],
                    [candidate.pk],
                )

    def test_collaborator_gets_403_and_private_project_is_hidden_from_outsider(self):
        self.authenticate(self.collaborator)
        collaborator_response = self.search()
        self.authenticate(self.outsider)
        outsider_response = self.search()

        self.assertEqual(collaborator_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(outsider_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_query_is_required_trimmed_and_has_length_limits(self):
        self.authenticate(self.leader)
        for params in ({}, {"q": ""}, {"q": "  аб  "}, {"q": "x" * 101}):
            with self.subTest(params=params):
                response = self.client.get(self.candidates_url(), params)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("q", response.data)

        candidate = self.create_named_user("candidate-trimmed", "Анна", "Смирнова")
        response = self.search("  СМирнова  ")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [candidate.pk])

    def test_searches_by_names_both_full_name_orders_and_email_prefix(self):
        candidate = self.create_named_user("candidate-searchable", "Иван", "Петров")
        email_prefix = candidate.email.split("@", maxsplit=1)[0]
        self.authenticate(self.leader)

        for query in (
            "иван",
            "петров",
            "иван петров",
            "петров иван",
            email_prefix,
        ):
            with self.subTest(query=query):
                response = self.search(query)
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(
                    [item["id"] for item in response.data],
                    [candidate.pk],
                )

    def test_response_contains_only_safe_profile_fields(self):
        candidate = self.create_named_user("candidate-safe-response", "Иван", "Петров")
        candidate.avatar = "https://example.com/avatar.png"
        candidate.save(update_fields=["avatar"])
        self.authenticate(self.leader)

        response = self.search()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            [
                {
                    "id": candidate.pk,
                    "display_name": "Иван Петров",
                    "avatar": "https://example.com/avatar.png",
                }
            ],
        )
        self.assertNotIn("email", response.data[0])

    def test_inactive_leader_collaborator_and_pending_recipient_are_excluded(self):
        inactive = self.create_named_user("candidate-inactive", is_active=False)
        pending = self.create_named_user("candidate-pending")
        Invite.objects.create(
            project=self.project,
            user=pending,
            invited_by=self.leader,
        )
        self.authenticate(self.leader)

        response = self.search("проект")
        pending_response = self.search("петров")

        result_ids = {item["id"] for item in response.data + pending_response.data}
        self.assertNotIn(inactive.pk, result_ids)
        self.assertNotIn(self.leader.pk, result_ids)
        self.assertNotIn(self.collaborator.pk, result_ids)
        self.assertNotIn(pending.pk, result_ids)

    def test_declined_and_revoked_invitation_history_does_not_block_candidate(self):
        declined = self.create_named_user("candidate-declined")
        revoked = self.create_named_user("candidate-revoked")
        Invite.objects.create(
            project=self.project,
            user=declined,
            invited_by=self.leader,
            is_accepted=False,
        )
        Invite.objects.create(
            project=self.project,
            user=revoked,
            invited_by=self.leader,
            is_revoked=True,
        )
        self.authenticate(self.leader)

        response = self.search()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {item["id"] for item in response.data},
            {declined.pk, revoked.pk},
        )

    def test_linked_program_limits_candidates_to_program_members(self):
        member = self.create_named_user("candidate-program-member")
        non_member = self.create_named_user("candidate-program-outsider")
        program = link_project_to_program(project=self.project)
        add_user_to_program(user=member, program=program)
        self.authenticate(self.leader)

        response = self.search()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [member.pk])
        self.assertNotIn(non_member.pk, [item["id"] for item in response.data])

    def test_results_are_stable_limited_to_twenty_and_do_not_write(self):
        candidates = [
            self.create_named_user(
                f"candidate-limit-{index}",
                "Одинаковое",
                "Имя",
            )
            for index in range(22)
        ]
        before = (
            Invite.objects.count(),
            Collaborator.objects.count(),
        )
        self.authenticate(self.leader)

        first = self.search("одинаковое")
        second = self.search("одинаковое")

        expected_ids = [candidate.pk for candidate in candidates[:20]]
        self.assertEqual([item["id"] for item in first.data], expected_ids)
        self.assertEqual([item["id"] for item in second.data], expected_ids)
        self.assertEqual(
            (Invite.objects.count(), Collaborator.objects.count()),
            before,
        )

    def test_candidate_list_has_bounded_query_count(self):
        for index in range(8):
            self.create_named_user(f"candidate-query-{index}")
        self.authenticate(self.leader)

        with CaptureQueriesContext(connection) as queries:
            response = self.search()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 8)
        self.assertLessEqual(len(queries), 4)

    def test_post_revalidates_eligibility_after_search(self):
        candidate = self.create_named_user("candidate-revalidated")
        self.authenticate(self.leader)
        self.assertEqual(self.search().status_code, status.HTTP_200_OK)
        add_collaborator(project=self.project, user=candidate)

        response = self.client.post(
            f"/projects/{self.project.pk}/workspace/invitations/",
            {"recipient_id": candidate.pk},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("recipient_id", response.data)
        self.assertFalse(
            Invite.objects.filter(project=self.project, user=candidate).exists()
        )

    @patch.object(
        ProjectInvitationCandidateSearchScopedRateThrottle,
        "rate",
        "1/min",
    )
    def test_search_has_dedicated_throttle(self):
        self.authenticate(self.leader)

        first = self.search()
        second = self.search()

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
