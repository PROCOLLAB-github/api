from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from chats.models import ProjectChat
from projects.models import Collaborator, Project

from .helpers import (
    add_program_member,
    create_industry,
    create_partner_program,
    create_project,
    create_project_context,
    create_user,
)


class ProjectCreateAndReadAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = create_user(prefix="project-api-user")
        self.client.force_authenticate(self.user)
        self.industry = create_industry()

    def test_create_project_sets_current_user_as_leader_and_creates_collaborator(self):
        response = self.client.post(
            "/projects/",
            {
                "name": "Research platform",
                "description": "Platform for applied research",
                "industry": self.industry.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        project = Project.objects.get(pk=response.data["id"])
        self.assertEqual(project.leader, self.user)
        self.assertEqual(response.data["leader"], self.user.id)
        self.assertTrue(
            Collaborator.objects.filter(
                project=project,
                user=self.user,
                role="Основатель",
            ).exists()
        )

    def test_create_published_project_creates_project_chat_and_shows_in_list(self):
        response = self.client.post(
            "/projects/",
            {
                "name": "Published research platform",
                "description": "Visible project",
                "industry": self.industry.id,
                "draft": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        project = Project.objects.get(pk=response.data["id"])
        self.assertFalse(project.draft)
        self.assertTrue(project.is_public)
        self.assertTrue(ProjectChat.objects.filter(project=project).exists())

        list_response = self.client.get("/projects/")

        self.assertEqual(list_response.status_code, 200)
        listed_ids = [item["id"] for item in list_response.data["results"]]
        self.assertIn(project.id, listed_ids)

    def test_draft_project_is_hidden_from_public_list(self):
        draft_project = create_project(
            leader=self.user,
            name="Draft project",
            draft=True,
        )
        published_project = create_project(
            leader=self.user,
            name="Published project",
            draft=False,
            is_public=True,
        )

        response = self.client.get("/projects/")

        self.assertEqual(response.status_code, 200)
        listed_ids = [item["id"] for item in response.data["results"]]
        self.assertNotIn(draft_project.id, listed_ids)
        self.assertIn(published_project.id, listed_ids)

    def test_project_detail_adds_view_for_authenticated_user(self):
        project = create_project(
            leader=self.user,
            name="Detail project",
            draft=False,
            is_public=True,
        )

        response = self.client.get(f"/projects/{project.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], project.id)
        self.assertEqual(response.data["name"], project.name)
        self.assertEqual(response.data["views_count"], 1)


class ProjectPutUpdateAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        context = create_project_context(
            user_prefix="project-put-leader",
            project_name="Initial project",
            draft=True,
        )
        self.user = context.user
        self.project = context.project
        self.industry = create_industry(name="Updated industry")
        self.client.force_authenticate(self.user)

    def _full_project_payload(self, **overrides):
        payload = {
            "name": "Updated project",
            "description": "Updated project description",
            "region": "Moscow",
            "industry": self.industry.id,
            "presentation_address": "https://example.com/presentation",
            "image_address": "https://example.com/image.png",
            "cover_image_address": "https://example.com/cover.png",
            "draft": False,
            "actuality": "Updated actuality",
            "problem": "Updated problem",
            "target_audience": "Updated target audience",
            "implementation_deadline": "2026-12-31",
            "trl": 5,
        }
        payload.update(overrides)
        return payload

    def test_put_updates_full_project_form_without_changing_leader(self):
        response = self.client.put(
            f"/projects/{self.project.id}/",
            self._full_project_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Updated project")
        self.assertEqual(self.project.description, "Updated project description")
        self.assertEqual(self.project.region, "Moscow")
        self.assertEqual(self.project.industry, self.industry)
        self.assertEqual(
            self.project.presentation_address,
            "https://example.com/presentation",
        )
        self.assertEqual(self.project.image_address, "https://example.com/image.png")
        self.assertEqual(
            self.project.cover_image_address,
            "https://example.com/cover.png",
        )
        self.assertFalse(self.project.draft)
        self.assertEqual(self.project.actuality, "Updated actuality")
        self.assertEqual(self.project.problem, "Updated problem")
        self.assertEqual(self.project.target_audience, "Updated target audience")
        self.assertEqual(str(self.project.implementation_deadline), "2026-12-31")
        self.assertEqual(self.project.trl, 5)
        self.assertEqual(self.project.leader, self.user)

    def test_put_binds_project_to_program_when_user_is_program_member(self):
        program = create_partner_program(name="PUT target program")
        member_profile = add_program_member(program, self.user)

        response = self.client.put(
            f"/projects/{self.project.id}/",
            self._full_project_payload(partner_program_id=program.id),
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        member_profile.refresh_from_db()
        self.assertTrue(
            self.project.program_links.filter(partner_program=program).exists()
        )
        self.assertEqual(member_profile.project, self.project)
        self.assertFalse(self.project.is_public)

    def test_non_leader_cannot_put_update_project(self):
        non_leader = create_user(prefix="project-put-non-leader")
        self.client.force_authenticate(non_leader)

        response = self.client.put(
            f"/projects/{self.project.id}/",
            self._full_project_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.project.refresh_from_db()
        self.assertNotEqual(self.project.name, "Updated project")
