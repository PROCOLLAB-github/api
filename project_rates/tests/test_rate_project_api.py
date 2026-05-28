from unittest.mock import patch

from django.test import TestCase

from rest_framework.test import APIClient

from project_rates.models import ProjectScore
from project_rates.tests.helpers import (
    create_rate_criteria,
    create_rate_expert,
    create_rate_program,
    create_rate_project,
    create_rate_user,
    link_project_to_program,
)


class RateProjectAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.program = create_rate_program(max_project_rates=2)
        self.expert = create_rate_expert(program=self.program)
        self.other_expert = create_rate_expert(
            prefix="rate-other-expert",
            program=self.program,
        )
        self.leader = create_rate_user(prefix="rate-leader")
        self.project = create_rate_project(leader=self.leader)
        link_project_to_program(self.program, self.project)
        self.criteria = create_rate_criteria(
            self.program,
            min_value=0,
            max_value=10,
        )

    def _rate_url(self, project_id: int | None = None) -> str:
        return f"/rate-project/rate/{project_id or self.project.id}"

    def _payload(self, criteria=None, value: str = "8") -> list[dict]:
        return [{"criterion_id": (criteria or self.criteria).id, "value": value}]

    @patch("project_rates.views.send_email.delay")
    def test_expert_can_rate_project_without_distribution(self, send_email_delay):
        self.client.force_authenticate(self.expert)

        response = self.client.post(
            self._rate_url(),
            self._payload(value="8"),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, {"success": True})
        self.assertTrue(
            ProjectScore.objects.filter(
                criteria=self.criteria,
                user=self.expert,
                project=self.project,
                value="8",
            ).exists()
        )
        send_email_delay.assert_called_once()

    @patch("project_rates.views.send_email.delay")
    def test_expert_can_update_existing_score(self, send_email_delay):
        ProjectScore.objects.create(
            criteria=self.criteria,
            user=self.expert,
            project=self.project,
            value="6",
        )
        self.client.force_authenticate(self.expert)

        response = self.client.post(
            self._rate_url(),
            self._payload(value="9"),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        scores = ProjectScore.objects.filter(
            criteria=self.criteria,
            user=self.expert,
            project=self.project,
        )
        self.assertEqual(scores.count(), 1)
        self.assertEqual(scores.get().value, "9")
        send_email_delay.assert_called_once()

    @patch("project_rates.views.send_email.delay")
    def test_rate_project_rejects_expert_without_program_membership(
        self,
        send_email_delay,
    ):
        outsider = create_rate_expert(prefix="rate-outsider")
        self.client.force_authenticate(outsider)

        response = self.client.post(
            self._rate_url(),
            self._payload(value="8"),
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data["error"],
            "you have no permission to rate this program",
        )
        self.assertFalse(ProjectScore.objects.filter(user=outsider).exists())
        send_email_delay.assert_not_called()

    @patch("project_rates.views.send_email.delay")
    def test_rate_project_rejects_project_not_linked_to_program(
        self,
        send_email_delay,
    ):
        unlinked_project = create_rate_project(
            leader=self.leader,
            name="Unlinked",
        )
        self.client.force_authenticate(self.expert)

        response = self.client.post(
            self._rate_url(unlinked_project.id),
            self._payload(value="8"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Project is not linked to the program")
        self.assertFalse(ProjectScore.objects.filter(project=unlinked_project).exists())
        send_email_delay.assert_not_called()

    @patch("project_rates.views.send_email.delay")
    def test_rate_project_rejects_criteria_from_different_programs(
        self,
        send_email_delay,
    ):
        other_program = create_rate_program(name="Other Rate Program")
        other_criteria = create_rate_criteria(other_program, min_value=0, max_value=10)
        self.client.force_authenticate(self.expert)

        response = self.client.post(
            self._rate_url(),
            [
                {"criterion_id": self.criteria.id, "value": "8"},
                {"criterion_id": other_criteria.id, "value": "7"},
            ],
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["error"],
            "All criteria must belong to the same program",
        )
        self.assertFalse(ProjectScore.objects.filter(project=self.project).exists())
        send_email_delay.assert_not_called()

    @patch("project_rates.views.send_email.delay")
    def test_rate_project_respects_max_project_rates_for_new_expert(
        self,
        send_email_delay,
    ):
        self.program.max_project_rates = 1
        self.program.save(update_fields=["max_project_rates"])
        ProjectScore.objects.create(
            criteria=self.criteria,
            user=self.expert,
            project=self.project,
            value="8",
        )
        self.client.force_authenticate(self.other_expert)

        response = self.client.post(
            self._rate_url(),
            self._payload(value="7"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {
                "error": "max project rates reached for this program",
                "max_project_rates": 1,
            },
        )
        self.assertFalse(ProjectScore.objects.filter(user=self.other_expert).exists())
        send_email_delay.assert_not_called()

    @patch("project_rates.views.send_email.delay")
    def test_rate_project_validates_numeric_limits(self, send_email_delay):
        self.client.force_authenticate(self.expert)

        response = self.client.post(
            self._rate_url(),
            self._payload(value="11"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Оценка этого критерия превысила", response.data["error"])
        self.assertFalse(ProjectScore.objects.filter(project=self.project).exists())
        send_email_delay.assert_not_called()

    @patch("project_rates.views.send_email.delay")
    def test_rate_project_validates_bool_value(self, send_email_delay):
        bool_criteria = create_rate_criteria(self.program, type="bool")
        self.client.force_authenticate(self.expert)

        response = self.client.post(
            self._rate_url(),
            self._payload(criteria=bool_criteria, value="yes"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("не соответствует формату", response.data["error"])
        self.assertFalse(ProjectScore.objects.filter(criteria=bool_criteria).exists())
        send_email_delay.assert_not_called()
