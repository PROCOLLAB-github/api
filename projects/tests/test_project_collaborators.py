from django.test import TestCase
from rest_framework.test import APIClient

from projects.models import Collaborator

from .helpers import (
    create_collaborator,
    create_project_context,
    create_user,
)


class ProjectCollaboratorRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        context = create_project_context(
            user_prefix="project-collaborator-leader",
            draft=True,
        )
        self.leader = context.user
        self.project = context.project
        self.client.force_authenticate(self.leader)

    def test_get_collaborators_returns_project_team(self):
        teammate = create_user(prefix="project-collaborator-teammate")
        create_collaborator(
            self.project,
            user=teammate,
            role="Engineer",
            specialization="Backend",
        )

        response = self.client.get(f"/projects/{self.project.id}/collaborators/")

        self.assertEqual(response.status_code, 200)
        collaborator_ids = [
            collaborator["user_id"] for collaborator in response.data["collaborators"]
        ]
        self.assertIn(self.leader.id, collaborator_ids)
        self.assertIn(teammate.id, collaborator_ids)

    def test_leader_can_delete_existing_collaborator(self):
        teammate = create_user(prefix="project-collaborator-delete")
        create_collaborator(self.project, user=teammate)

        response = self.client.delete(
            f"/projects/{self.project.id}/collaborators/?id={teammate.id}",
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            Collaborator.objects.filter(project=self.project, user=teammate).exists()
        )

    def test_collaborator_can_leave_project(self):
        teammate = create_user(prefix="project-collaborator-leave")
        create_collaborator(self.project, user=teammate)
        self.client.force_authenticate(teammate)

        response = self.client.delete(
            f"/projects/{self.project.id}/collaborators/leave/"
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            Collaborator.objects.filter(project=self.project, user=teammate).exists()
        )

    def test_leader_cannot_leave_project_as_regular_collaborator(self):
        response = self.client.delete(
            f"/projects/{self.project.id}/collaborators/leave/"
        )

        self.assertEqual(response.status_code, 422)
        self.assertTrue(
            Collaborator.objects.filter(project=self.project, user=self.leader).exists()
        )

    def test_leader_can_switch_project_leader_to_existing_collaborator(self):
        teammate = create_user(prefix="project-collaborator-new-leader")
        create_collaborator(
            self.project,
            user=teammate,
            role="Engineer",
        )

        response = self.client.patch(
            (
                f"/projects/{self.project.id}/collaborators/"
                f"{teammate.id}/switch-leader/"
            )
        )

        self.assertEqual(response.status_code, 204)
        self.project.refresh_from_db()
        self.assertEqual(self.project.leader, teammate)

    def test_switch_leader_rejects_user_who_is_not_project_collaborator(self):
        outsider = create_user(prefix="project-collaborator-outsider")

        response = self.client.patch(
            (
                f"/projects/{self.project.id}/collaborators/"
                f"{outsider.id}/switch-leader/"
            )
        )

        self.assertEqual(response.status_code, 422)
        self.project.refresh_from_db()
        self.assertEqual(self.project.leader, self.leader)
