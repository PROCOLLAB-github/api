from unittest.mock import patch

from django.test import TestCase

from rest_framework.test import APIClient

from project_rates.models import ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import (
    create_rate_criteria,
    create_rate_expert,
    create_rate_program,
    create_rate_project,
    create_rate_user,
    link_project_to_program,
)


class DistributedEvaluationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.program = create_rate_program(max_project_rates=2)
        self.expert_user = create_rate_expert(prefix="distributed-expert")
        self.other_expert_user = create_rate_expert(prefix="distributed-other-expert")
        self.expert_user.expert.programs.add(self.program)
        self.other_expert_user.expert.programs.add(self.program)

        self.leader = create_rate_user(prefix="distributed-leader")
        self.project_1 = create_rate_project(
            leader=self.leader,
            name="Distributed Project 1",
        )
        self.project_2 = create_rate_project(
            leader=self.leader,
            name="Distributed Project 2",
        )
        link_project_to_program(self.program, self.project_1)
        link_project_to_program(self.program, self.project_2)

        self.criteria = create_rate_criteria(
            self.program,
            name="Impact",
            min_value=0,
            max_value=10,
        )

    def _projects_url(self) -> str:
        return f"/rate-project/{self.program.id}"

    def _rate_url(self, project_id: int) -> str:
        return f"/rate-project/rate/{project_id}"

    def test_list_projects_without_distribution_returns_all_program_projects(self):
        self.client.force_authenticate(self.expert_user)

        response = self.client.get(self._projects_url())

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data["results"]}
        self.assertSetEqual(returned_ids, {self.project_1.id, self.project_2.id})

    def test_list_projects_with_distribution_returns_only_assigned_projects(self):
        self.program.is_distributed_evaluation = True
        self.program.save(update_fields=["is_distributed_evaluation"])
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=self.project_1,
            expert=self.expert_user.expert,
        )
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=self.project_2,
            expert=self.other_expert_user.expert,
        )

        self.client.force_authenticate(self.expert_user)
        response = self.client.get(self._projects_url())

        self.assertEqual(response.status_code, 200)
        returned_ids = [item["id"] for item in response.data["results"]]
        self.assertListEqual(returned_ids, [self.project_1.id])

    @patch("project_rates.views.send_email.delay")
    def test_rate_project_with_distribution_rejects_unassigned_expert(self, _mock_delay):
        self.program.is_distributed_evaluation = True
        self.program.save(update_fields=["is_distributed_evaluation"])

        self.client.force_authenticate(self.expert_user)
        response = self.client.post(
            self._rate_url(self.project_1.id),
            [{"criterion_id": self.criteria.id, "value": "8"}],
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["error"], "you are not assigned to rate this project"
        )
        self.assertFalse(ProjectScore.objects.filter(project=self.project_1).exists())

    @patch("project_rates.views.send_email.delay")
    def test_rate_project_with_distribution_accepts_assigned_expert(self, mock_delay):
        self.program.is_distributed_evaluation = True
        self.program.save(update_fields=["is_distributed_evaluation"])
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=self.project_1,
            expert=self.expert_user.expert,
        )

        self.client.force_authenticate(self.expert_user)
        response = self.client.post(
            self._rate_url(self.project_1.id),
            [{"criterion_id": self.criteria.id, "value": "8"}],
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            ProjectScore.objects.filter(
                project=self.project_1,
                user=self.expert_user,
                criteria=self.criteria,
                value="8",
            ).exists()
        )
        mock_delay.assert_called_once()
