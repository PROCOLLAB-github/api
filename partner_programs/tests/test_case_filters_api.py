"""Reserved case reuses the existing schema/manager/expert filters unchanged."""

from django.test import TestCase
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramFieldValue
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_project,
    create_project,
    create_user,
)
from partner_programs.tests.test_case_fields import create_case_field
from project_rates.tests.helpers import create_rate_expert


class ProgramCaseFilterAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.program = create_partner_program()
        self.field = create_case_field(self.program)
        self.manager = create_user()
        self.program.managers.add(self.manager)
        self.expert = create_rate_expert(program=self.program)
        self.projects = [create_project(is_public=True), create_project(is_public=True)]
        for project, value in zip(self.projects, ["A", "B"]):
            link = create_program_project(self.program, project=project)
            PartnerProgramFieldValue.objects.create(
                program_project=link, field=self.field, value_text=value
            )
        # Same Project has a different case in another program; never mix its values.
        other = create_partner_program()
        other_field = create_case_field(other)
        other_link = create_program_project(other, project=self.projects[0])
        PartnerProgramFieldValue.objects.create(
            program_project=other_link, field=other_field, value_text="B"
        )

    def test_expert_and_manager_get_identical_filterable_case_schema(self):
        self.client.force_authenticate(self.manager)
        manager = self.client.get(f"/programs/{self.program.pk}/filters/")
        self.client.force_authenticate(self.expert)
        expert = self.client.get(f"/programs/{self.program.pk}/filters/")
        self.assertEqual(manager.status_code, 200)
        self.assertEqual(expert.status_code, 200)
        self.assertEqual(manager.data, expert.data)
        self.assertIn("case", str(expert.data))
        self.assertEqual(
            self.client.post(
                f"/programs/{self.program.pk}/filters/", {}, format="json"
            ).status_code,
            405,
        )

    def assert_filtered_projects(self, user, url):
        self.client.force_authenticate(user)
        for values, expected in (
            (["A"], [self.projects[0].pk]),
            (["B"], [self.projects[1].pk]),
            (["A", "B"], [p.pk for p in self.projects]),
        ):
            with self.subTest(values=values):
                response = self.client.post(
                    url, {"filters": {"case": values}}, format="json"
                )
                self.assertEqual(response.status_code, 200, response.data)
                self.assertCountEqual(
                    [item["id"] for item in response.data["results"]], expected
                )

    def test_manager_case_filter_returns_only_selected_program_cases(self):
        self.assert_filtered_projects(
            self.manager, f"/programs/{self.program.pk}/projects/filter/"
        )

    def test_expert_rating_case_filter_preserves_existing_or_semantics(self):
        self.assert_filtered_projects(self.expert, f"/rate-project/{self.program.pk}")
