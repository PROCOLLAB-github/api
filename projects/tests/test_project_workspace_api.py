from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from partner_programs.models import Application
from projects.tests.helpers import (
    create_collaborator,
    create_industry,
    create_partner_program,
    create_project,
    create_user,
)


class ProjectWorkspaceAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.leader = create_user(prefix="workspace-leader")
        self.collaborator_user = create_user(prefix="workspace-collaborator")
        self.outsider = create_user(prefix="workspace-outsider")
        self.staff = create_user(prefix="workspace-staff")
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])
        self.industry = create_industry(name="Workspace industry")

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_workspace_endpoints_require_authentication(self):
        project = create_project(leader=self.leader)

        self.assertEqual(self.client.get("/projects/catalog/").status_code, 401)
        self.assertEqual(self.client.get("/projects/my/").status_code, 401)
        self.assertEqual(
            self.client.get(f"/projects/{project.pk}/workspace/").status_code,
            401,
        )

    def test_catalog_returns_only_public_published_projects(self):
        visible = create_project(
            leader=self.leader,
            draft=False,
            is_public=True,
            industry=self.industry,
        )
        create_project(leader=self.leader, draft=True, is_public=True)
        create_project(leader=self.leader, draft=False, is_public=False)
        self.authenticate(self.outsider)

        response = self.client.get("/projects/catalog/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [visible.pk])

    def test_catalog_supports_search_and_industry_filter(self):
        match = create_project(
            leader=self.leader,
            name="Solar laboratory",
            draft=False,
            is_public=True,
            industry=self.industry,
        )
        create_project(
            leader=self.leader,
            name="Other project",
            draft=False,
            is_public=True,
        )
        self.authenticate(self.outsider)

        response = self.client.get(
            "/projects/catalog/",
            {"search": "Solar", "industry": self.industry.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [match.pk])

    def test_my_projects_include_private_draft_for_leader_and_collaborator(self):
        led = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )
        joined = create_project(
            leader=self.outsider,
            draft=True,
            is_public=False,
        )
        create_collaborator(joined, user=self.leader)
        self.authenticate(self.leader)

        response = self.client.get("/projects/my/")

        self.assertEqual(response.status_code, 200)
        by_id = {item["id"]: item for item in response.data["results"]}
        self.assertEqual(by_id[led.pk]["current_user_role"], "leader")
        self.assertTrue(by_id[led.pk]["can_edit"])
        self.assertTrue(by_id[led.pk]["can_use_in_application"])
        self.assertEqual(by_id[joined.pk]["current_user_role"], "collaborator")
        self.assertFalse(by_id[joined.pk]["can_edit"])
        self.assertFalse(by_id[joined.pk]["can_use_in_application"])

    def test_list_contract_includes_related_activities_without_n_plus_one(self):
        projects = [
            create_project(leader=self.leader, draft=True, is_public=False)
            for _index in range(3)
        ]
        for index, project in enumerate(projects):
            program = create_partner_program(name=f"Activity {index}")
            Application.objects.create(
                program=program,
                user=self.leader,
                created_by=self.leader,
                project=project,
            )
        self.authenticate(self.leader)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/projects/my/", {"limit": 20})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 3)
        self.assertTrue(response.data["results"][0]["activities"])
        self.assertLessEqual(len(queries), 10)

    def test_workspace_detail_hides_private_project_from_outsider(self):
        project = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )
        self.authenticate(self.outsider)

        response = self.client.get(f"/projects/{project.pk}/workspace/")

        self.assertEqual(response.status_code, 404)

    def test_workspace_detail_is_public_but_private_data_is_not_exposed(self):
        project = create_project(
            leader=self.leader,
            draft=False,
            is_public=True,
            industry=self.industry,
        )
        self.authenticate(self.outsider)

        response = self.client.get(f"/projects/{project.pk}/workspace/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["leader"]["id"], self.leader.pk)
        self.assertNotIn("email", response.data["leader"])
        self.assertNotIn("phone_number", response.data["leader"])
        self.assertNotIn("form_data", response.data)

    def test_leader_can_patch_only_workspace_fields(self):
        project = create_project(leader=self.leader, draft=True, is_public=False)
        self.authenticate(self.leader)

        response = self.client.patch(
            f"/projects/{project.pk}/workspace/",
            {"name": "Updated", "draft": False, "is_public": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.name, "Updated")
        self.assertFalse(project.draft)
        self.assertTrue(project.is_public)

    def test_collaborator_cannot_patch_and_leader_cannot_replace_leader(self):
        project = create_project(leader=self.leader, draft=True, is_public=False)
        create_collaborator(project, user=self.collaborator_user)
        self.authenticate(self.collaborator_user)
        forbidden = self.client.patch(
            f"/projects/{project.pk}/workspace/",
            {"name": "Forbidden"},
            format="json",
        )

        self.authenticate(self.leader)
        immutable = self.client.patch(
            f"/projects/{project.pk}/workspace/",
            {"leader": self.outsider.pk},
            format="json",
        )

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(immutable.status_code, 400)
        project.refresh_from_db()
        self.assertEqual(project.leader, self.leader)

    def test_staff_can_patch_private_project(self):
        project = create_project(leader=self.leader, draft=True, is_public=False)
        self.authenticate(self.staff)

        response = self.client.patch(
            f"/projects/{project.pk}/workspace/",
            {"description": "Administrative correction"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.description, "Administrative correction")

    def test_legacy_patch_remains_partial(self):
        project = create_project(
            leader=self.leader,
            description="Must remain",
            draft=True,
        )
        self.authenticate(self.leader)

        response = self.client.patch(
            f"/projects/{project.pk}/",
            {"name": "Legacy partial update"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.name, "Legacy partial update")
        self.assertEqual(project.description, "Must remain")


class ApplicationProjectSummaryTests(TestCase):
    def test_application_response_keeps_project_id_and_adds_summary(self):
        client = APIClient()
        user = create_user(prefix="application-project-summary")
        program = create_partner_program()
        project = create_project(
            leader=user,
            draft=True,
            is_public=False,
        )
        application = Application.objects.create(
            program=program,
            user=user,
            created_by=user,
            project=project,
        )
        client.force_authenticate(user=user)

        response = client.get(f"/applications/{application.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["project"], project.pk)
        self.assertEqual(
            response.data["project_summary"],
            {
                "id": project.pk,
                "name": project.name,
                "draft": True,
                "is_public": False,
            },
        )

    def test_submitted_application_cannot_replace_reused_project(self):
        client = APIClient()
        user = create_user(prefix="application-project-immutable")
        program = create_partner_program()
        original = create_project(leader=user, draft=True, is_public=False)
        replacement = create_project(leader=user, draft=True, is_public=False)
        application = Application.objects.create(
            program=program,
            user=user,
            created_by=user,
            project=original,
            status=Application.STATUS_SUBMITTED,
        )
        client.force_authenticate(user=user)

        response = client.patch(
            f"/applications/{application.pk}/",
            {"project_id": replacement.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        application.refresh_from_db()
        self.assertEqual(application.project, original)
