from django.test import TestCase
from rest_framework.test import APIClient

from projects.models import Company, ProjectCompany, Resource

from .helpers import (
    create_company,
    create_project_context,
    create_resource,
)


class ProjectCompanyRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        context = create_project_context(
            user_prefix="project-company-user",
            draft=True,
        )
        self.user = context.user
        self.project = context.project
        self.client.force_authenticate(self.user)

    def test_company_upsert_creates_company_and_project_link(self):
        response = self.client.post(
            f"/projects/{self.project.id}/companies/",
            {
                "name": "Industrial partner",
                "inn": "7701234567",
                "contribution": "Equipment",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        company = Company.objects.get(inn="7701234567")
        link = ProjectCompany.objects.get(project=self.project, company=company)
        self.assertEqual(link.contribution, "Equipment")
        self.assertEqual(response.data["company"]["id"], company.id)

    def test_company_upsert_updates_existing_project_link_without_duplicate(self):
        company = create_company(inn="7707654321")
        ProjectCompany.objects.create(
            project=self.project,
            company=company,
            contribution="Initial contribution",
        )

        response = self.client.post(
            f"/projects/{self.project.id}/companies/",
            {
                "name": company.name,
                "inn": company.inn,
                "contribution": "Updated contribution",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            ProjectCompany.objects.filter(project=self.project, company=company).count(),
            1,
        )
        link = ProjectCompany.objects.get(project=self.project, company=company)
        self.assertEqual(link.contribution, "Updated contribution")


class ProjectResourceRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        context = create_project_context(
            user_prefix="project-resource-user",
            draft=True,
        )
        self.user = context.user
        self.project = context.project
        self.client.force_authenticate(self.user)

    def test_create_resource_without_partner_company(self):
        response = self.client.post(
            f"/projects/{self.project.id}/resources/",
            {
                "type": Resource.ResourceType.INFORMATION,
                "description": "Need media coverage",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        resource = Resource.objects.get(pk=response.data["id"])
        self.assertEqual(resource.project, self.project)
        self.assertIsNone(resource.partner_company)

    def test_create_resource_accepts_only_project_partner_company(self):
        partner_company = create_company(inn="7701111111")
        ProjectCompany.objects.create(project=self.project, company=partner_company)

        response = self.client.post(
            f"/projects/{self.project.id}/resources/",
            {
                "type": Resource.ResourceType.INFRASTRUCTURE,
                "description": "Need laboratory",
                "partner_company": partner_company.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        resource = Resource.objects.get(pk=response.data["id"])
        self.assertEqual(resource.partner_company, partner_company)

    def test_create_resource_rejects_company_not_linked_to_project(self):
        foreign_company = create_company(inn="7702222222")

        response = self.client.post(
            f"/projects/{self.project.id}/resources/",
            {
                "type": Resource.ResourceType.INFRASTRUCTURE,
                "description": "Need laboratory",
                "partner_company": foreign_company.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("partner_company", response.data)

    def test_resource_helper_creates_valid_partner_link_when_company_is_given(self):
        company = create_company(inn="7703333333")

        resource = create_resource(self.project, partner_company=company)

        self.assertEqual(resource.partner_company, company)
        self.assertTrue(
            ProjectCompany.objects.filter(
                project=self.project,
                company=company,
            ).exists()
        )
