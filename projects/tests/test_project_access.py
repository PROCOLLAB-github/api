from django.test import TestCase
from rest_framework.test import APIClient

from .helpers import (
    create_collaborator,
    create_project,
    create_project_context,
    create_user,
)


class ProjectVisibilityRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_private_project_is_hidden_from_unrelated_user(self):
        project = create_project(draft=False, is_public=False)
        unrelated_user = create_user(prefix="unrelated-project-user")
        self.client.force_authenticate(unrelated_user)

        response = self.client.get(f"/projects/{project.id}/")

        self.assertEqual(response.status_code, 403)

    def test_private_project_is_available_to_leader(self):
        context = create_project_context(draft=False, is_public=False)
        self.client.force_authenticate(context.user)

        response = self.client.get(f"/projects/{context.project.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], context.project.id)

    def test_private_project_is_available_to_collaborator(self):
        project = create_project(draft=False, is_public=False)
        collaborator = create_collaborator(project).user
        self.client.force_authenticate(collaborator)

        response = self.client.get(f"/projects/{project.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], project.id)
