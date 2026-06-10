from django.test import TestCase
from rest_framework.test import APIClient

from .helpers import (
    add_program_member,
    create_collaborator,
    create_industry,
    create_partner_program,
    create_project,
    create_user,
    link_project_to_program,
)


class ProjectListFilterRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="project-filter-user")
        self.client.force_authenticate(self.user)

    def _project_ids(self, response):
        self.assertEqual(response.status_code, 200)
        return {project["id"] for project in response.data["results"]}

    def test_filter_by_industry(self):
        target_industry = create_industry(name="Target industry")
        other_industry = create_industry(name="Other industry")
        target_project = create_project(
            leader=self.user,
            industry=target_industry,
            draft=False,
            is_public=True,
        )
        other_project = create_project(
            leader=self.user,
            industry=other_industry,
            draft=False,
            is_public=True,
        )

        response = self.client.get("/projects/", {"industry": target_industry.id})

        project_ids = self._project_ids(response)
        self.assertIn(target_project.id, project_ids)
        self.assertNotIn(other_project.id, project_ids)

    def test_filter_by_leader(self):
        other_leader = create_user(prefix="project-filter-other-leader")
        target_project = create_project(
            leader=self.user,
            draft=False,
            is_public=True,
        )
        other_project = create_project(
            leader=other_leader,
            draft=False,
            is_public=True,
        )

        response = self.client.get("/projects/", {"leader": self.user.id})

        project_ids = self._project_ids(response)
        self.assertIn(target_project.id, project_ids)
        self.assertNotIn(other_project.id, project_ids)

    def test_filter_by_partner_program(self):
        target_program = create_partner_program(name="Target program")
        other_program = create_partner_program(name="Other program")
        add_program_member(target_program, self.user)
        add_program_member(other_program, self.user)
        target_project = create_project(draft=False, is_public=True)
        other_project = create_project(draft=False, is_public=True)
        link_project_to_program(target_project, target_program)
        link_project_to_program(other_project, other_program)

        response = self.client.get(
            "/projects/",
            {"partner_program": target_program.id},
        )

        project_ids = self._project_ids(response)
        self.assertIn(target_project.id, project_ids)
        self.assertNotIn(other_project.id, project_ids)

    def test_filter_by_is_company(self):
        company_project = create_project(draft=False, is_public=True)
        company_project.is_company = True
        company_project.save(update_fields=["is_company"])
        regular_project = create_project(draft=False, is_public=True)

        response = self.client.get("/projects/", {"is_company": "true"})

        project_ids = self._project_ids(response)
        self.assertIn(company_project.id, project_ids)
        self.assertNotIn(regular_project.id, project_ids)

    def test_filter_by_collaborator_user_in(self):
        collaborator = create_user(prefix="project-filter-collaborator")
        target_project = create_project(draft=False, is_public=True)
        other_project = create_project(draft=False, is_public=True)
        create_collaborator(target_project, user=collaborator)

        response = self.client.get(
            "/projects/",
            {"collaborator__user__in": str(collaborator.id)},
        )

        project_ids = self._project_ids(response)
        self.assertIn(target_project.id, project_ids)
        self.assertNotIn(other_project.id, project_ids)
