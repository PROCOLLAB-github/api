from django.test import TestCase

from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramField, PartnerProgramFieldValue
from project_rates.models import ProjectScore
from project_rates.tests.helpers import (
    create_rate_criteria,
    create_rate_expert,
    create_rate_program,
    create_rate_project,
    create_rate_user,
    link_project_to_program,
)


class ProjectListForRateAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.program = create_rate_program(max_project_rates=3)
        self.expert = create_rate_expert(program=self.program)
        self.leader = create_rate_user(prefix="rate-list-leader")
        self.project_1 = create_rate_project(
            leader=self.leader,
            name="Filtered Project",
        )
        self.project_2 = create_rate_project(
            leader=self.leader,
            name="Other Project",
        )
        self.link_1 = link_project_to_program(self.program, self.project_1)
        self.link_2 = link_project_to_program(self.program, self.project_2)
        self.criteria = create_rate_criteria(
            self.program,
            min_value=0,
            max_value=10,
        )

    def _projects_url(self) -> str:
        return f"/rate-project/{self.program.id}"

    def test_post_filters_projects_by_program_field_values(self):
        field = PartnerProgramField.objects.create(
            partner_program=self.program,
            name="track",
            label="Track",
            field_type="select",
            show_filter=True,
            options="FinTech|EdTech",
        )
        PartnerProgramFieldValue.objects.create(
            program_project=self.link_1,
            field=field,
            value_text="FinTech",
        )
        PartnerProgramFieldValue.objects.create(
            program_project=self.link_2,
            field=field,
            value_text="EdTech",
        )
        self.client.force_authenticate(self.expert)

        response = self.client.post(
            self._projects_url(),
            {"filters": {"track": ["FinTech"]}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        returned_ids = [item["id"] for item in response.data["results"]]
        self.assertEqual(returned_ids, [self.project_1.id])

    def test_list_marks_current_expert_score_and_program_rate_limits(self):
        ProjectScore.objects.create(
            criteria=self.criteria,
            user=self.expert,
            project=self.project_1,
            value="9",
        )
        self.client.force_authenticate(self.expert)

        response = self.client.get(self._projects_url())

        self.assertEqual(response.status_code, 200)
        project_data = next(
            item for item in response.data["results"] if item["id"] == self.project_1.id
        )
        self.assertTrue(project_data["scored"])
        self.assertEqual(project_data["rated_experts"], [self.expert.id])
        self.assertEqual(project_data["rated_count"], 1)
        self.assertEqual(project_data["max_rates"], 3)
        self.assertEqual(project_data["criterias"][0]["value"], "9")

    def test_list_returns_criterias_when_current_expert_has_no_scores(self):
        self.client.force_authenticate(self.expert)

        response = self.client.get(self._projects_url())

        self.assertEqual(response.status_code, 200)
        project_data = next(
            item for item in response.data["results"] if item["id"] == self.project_1.id
        )
        self.assertFalse(project_data["scored"])
        self.assertEqual(project_data["rated_experts"], [])
        self.assertEqual(project_data["rated_count"], 0)
        criteria_ids = {item["id"] for item in project_data["criterias"]}
        self.assertIn(self.criteria.id, criteria_ids)
