from django.test import TestCase
from rest_framework.test import APIClient

from projects import team_service
from projects.models import Collaborator
from projects.tests.helpers import (
    create_collaborator,
    create_project_context,
    create_user,
)


class TeamSecurityTests(TestCase):
    def setUp(self):
        context = create_project_context(draft=True)
        self.project, self.leader = context.project, context.user
        self.member = create_user()
        create_collaborator(self.project, user=self.member)
        self.outsider = create_user()
        self.client = APIClient()
        self.remove_url = f"/projects/{self.project.pk}/collaborators/"
        self.switch_url = f"{self.remove_url}{self.member.pk}/switch-leader/"

    def assert_error(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code, response.data)
        self.assertEqual(response.data["code"], code)

    def test_outsider_cannot_remove_or_switch_public_or_private_project(self):
        self.client.force_authenticate(self.outsider)
        for is_public in (True, False):
            with self.subTest(is_public=is_public):
                self.project.is_public = is_public
                self.project.save(update_fields=["is_public"])
                for response in (
                    self.client.delete(self.remove_url, {"id": self.member.pk}),
                    self.client.patch(self.switch_url),
                ):
                    self.assert_error(response, 403, "not_project_team_manager")
                self.project.refresh_from_db()
                self.assertEqual(self.project.leader_id, self.leader.pk)
                self.assertTrue(
                    Collaborator.objects.filter(
                        project=self.project, user=self.member
                    ).exists()
                )

    def test_read_involvement_does_not_grant_team_management(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.get(self.remove_url).status_code, 200)
        self.assert_error(
            self.client.patch(self.switch_url), 403, "not_project_team_manager"
        )
        self.assert_error(
            self.client.delete(f"{self.remove_url}?id={self.outsider.pk}"),
            403,
            "not_project_team_manager",
        )

    def test_leader_self_removal_is_controlled(self):
        self.client.force_authenticate(self.leader)
        self.assert_error(
            self.client.delete(f"{self.remove_url}?id={self.leader.pk}"),
            422,
            "leader_cannot_leave",
        )

    def test_missing_or_repeated_removal_is_controlled(self):
        self.client.force_authenticate(self.leader)
        url = f"{self.remove_url}?id={self.member.pk}"
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assert_error(self.client.delete(url), 422, "collaborator_not_found")

    def test_malformed_collaborator_ids_are_controlled(self):
        self.client.force_authenticate(self.leader)
        for query in ("", "?id=", "?id=7/", "?id=text", "?id=-1"):
            with self.subTest(query=query):
                self.assert_error(
                    self.client.delete(self.remove_url + query),
                    422,
                    "invalid_collaborator_id",
                )

    def test_direct_add_is_explicitly_unsupported_for_leader(self):
        self.client.force_authenticate(self.leader)
        self.assert_error(
            self.client.post(self.remove_url, {}, format="json"),
            405,
            "direct_member_add_unsupported",
        )

    def test_direct_add_rejects_outsider_before_input_validation(self):
        self.client.force_authenticate(self.outsider)
        self.assert_error(
            self.client.post(self.remove_url, {}, format="json"),
            403,
            "not_project_team_manager",
        )

    def test_service_rechecks_actor_without_http_permission_gate(self):
        for operation in (team_service.remove_member, team_service.switch_leader):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(team_service.TeamError) as raised:
                    operation(
                        project_id=self.project.pk,
                        user_id=self.member.pk,
                        actor=self.outsider,
                    )
                self.assertEqual(raised.exception.status_code, 403)

    def test_former_leader_cannot_manage_after_switch(self):
        self.client.force_authenticate(self.leader)
        self.assertEqual(self.client.patch(self.switch_url).status_code, 204)
        self.assert_error(
            self.client.delete(f"{self.remove_url}?id={self.member.pk}"),
            403,
            "not_project_team_manager",
        )

    def test_missing_project_returns_404(self):
        self.client.force_authenticate(self.leader)
        self.assertEqual(
            self.client.patch(
                f"/projects/2147483647/collaborators/{self.member.pk}/switch-leader/"
            ).status_code,
            404,
        )
