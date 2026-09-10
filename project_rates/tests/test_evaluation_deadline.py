from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from partner_programs.models import (
    Application,
    Evaluation,
    EvaluationScore,
    Submission,
    SubmissionExpertAssignment,
)
from partner_programs.tests.helpers import create_program_member, create_user
from project_rates.models import ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import (
    create_rate_criteria,
    create_rate_expert,
    create_rate_program,
    create_rate_project,
    create_rate_user,
    link_project_to_program,
)


class EvaluationDeadlineAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.now = timezone.now()
        self.client = APIClient()
        self.program = create_rate_program(
            datetime_evaluation_ends=self.now + timedelta(days=1),
            max_project_rates=2,
        )
        self.expert = create_rate_expert(program=self.program)
        self.leader = create_rate_user(prefix="deadline-leader")
        self.project = create_rate_project(leader=self.leader)
        self.program_link = link_project_to_program(self.program, self.project)
        self.criteria = create_rate_criteria(
            self.program,
            min_value=0,
            max_value=10,
        )
        self.client.force_authenticate(self.expert)

    def _url(self, project=None):
        return f"/rate-project/rate/{(project or self.project).pk}"

    def _payload(self, *, criteria=None, value="8"):
        return [
            {
                "criterion_id": (criteria or self.criteria).pk,
                "value": value,
            }
        ]

    def _set_deadline(self, deadline):
        self.program.datetime_evaluation_ends = deadline
        self.program.save(update_fields=["datetime_evaluation_ends"])

    def _post(self, *, payload=None, project=None, now=None):
        with patch(
            "project_rates.services.timezone.now",
            return_value=now or self.now,
        ), patch("project_rates.services.send_email.delay") as send_email_delay:
            response = self.client.post(
                self._url(project),
                payload if payload is not None else self._payload(),
                format="json",
            )
        return response, send_email_delay

    def assert_deadline_error(self, response):
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.data,
            {
                "error": "evaluation_deadline_passed",
                "detail": "Срок оценивания завершён.",
            },
        )

    def test_null_deadline_allows_initial_rating(self):
        self._set_deadline(None)

        response, send_email_delay = self._post()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(ProjectScore.objects.count(), 1)
        send_email_delay.assert_called_once()

    def test_future_deadline_allows_initial_rating(self):
        response, send_email_delay = self._post()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(ProjectScore.objects.count(), 1)
        send_email_delay.assert_called_once()

    def test_exact_deadline_allows_initial_rating(self):
        self._set_deadline(self.now)

        response, send_email_delay = self._post(now=self.now)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(ProjectScore.objects.count(), 1)
        send_email_delay.assert_called_once()

    def test_after_deadline_rejects_initial_rating_without_side_effects(self):
        self._set_deadline(self.now - timedelta(microseconds=1))
        project_before = self._row(self.project)
        link_before = self._row(self.program_link)

        response, send_email_delay = self._post(now=self.now)

        self.assert_deadline_error(response)
        self.assertFalse(ProjectScore.objects.exists())
        self.assertEqual(self._row(self.project), project_before)
        self.assertEqual(self._row(self.program_link), link_before)
        send_email_delay.assert_not_called()

    def test_after_deadline_rejects_edit_and_preserves_existing_scores(self):
        existing = ProjectScore.objects.create(
            criteria=self.criteria,
            user=self.expert,
            project=self.project,
            value="6",
        )
        other_criteria = create_rate_criteria(
            self.program,
            name="Feasibility",
            min_value=0,
            max_value=10,
        )
        self._set_deadline(self.now - timedelta(seconds=1))

        response, send_email_delay = self._post(
            payload=[
                {"criterion_id": self.criteria.pk, "value": "9"},
                {"criterion_id": other_criteria.pk, "value": "7"},
            ]
        )

        self.assert_deadline_error(response)
        existing.refresh_from_db()
        self.assertEqual(existing.value, "6")
        self.assertEqual(ProjectScore.objects.count(), 1)
        self.assertEqual(
            ProjectScore.objects.values("user_id").distinct().count(),
            1,
        )
        send_email_delay.assert_not_called()

    def test_deadline_changes_are_used_on_every_request(self):
        response, _ = self._post(payload=self._payload(value="5"))
        self.assertEqual(response.status_code, 201)

        self._set_deadline(self.now - timedelta(seconds=1))
        response, send_email_delay = self._post(payload=self._payload(value="6"))
        self.assert_deadline_error(response)
        self.assertEqual(ProjectScore.objects.get().value, "5")
        send_email_delay.assert_not_called()

        self._set_deadline(self.now + timedelta(seconds=1))
        response, send_email_delay = self._post(payload=self._payload(value="7"))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ProjectScore.objects.get().value, "7")
        send_email_delay.assert_called_once()

    def test_distributed_assignment_is_checked_before_deadline(self):
        self.program.is_distributed_evaluation = True
        self.program.datetime_evaluation_ends = self.now - timedelta(seconds=1)
        self.program.save(
            update_fields=[
                "is_distributed_evaluation",
                "datetime_evaluation_ends",
            ]
        )

        response, send_email_delay = self._post()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["error"],
            "you are not assigned to rate this project",
        )
        send_email_delay.assert_not_called()

        assignment = ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=self.project,
            expert=self.expert.expert,
        )
        assignment_before = self._row(assignment)
        response, send_email_delay = self._post()
        self.assert_deadline_error(response)
        self.assertEqual(self._row(assignment), assignment_before)
        send_email_delay.assert_not_called()

        self._set_deadline(self.now + timedelta(seconds=1))
        response, send_email_delay = self._post()
        self.assertEqual(response.status_code, 201)
        send_email_delay.assert_called_once()

    def test_multi_program_deadline_is_selected_from_request_criteria(self):
        self._set_deadline(self.now - timedelta(seconds=1))
        other_program = create_rate_program(
            name="Future deadline program",
            datetime_evaluation_ends=self.now + timedelta(seconds=1),
        )
        other_criteria = create_rate_criteria(
            other_program,
            min_value=0,
            max_value=10,
        )
        self.expert.expert.programs.add(other_program)
        link_project_to_program(other_program, self.project)

        response, _ = self._post(payload=self._payload(criteria=self.criteria))
        self.assert_deadline_error(response)

        response, send_email_delay = self._post(
            payload=self._payload(criteria=other_criteria)
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(ProjectScore.objects.filter(criteria=other_criteria).exists())
        send_email_delay.assert_called_once()

    def test_deadline_precedes_max_rates_after_security_checks(self):
        self.program.max_project_rates = 1
        self.program.save(update_fields=["max_project_rates"])
        ProjectScore.objects.create(
            criteria=self.criteria,
            user=self.expert,
            project=self.project,
            value="8",
        )
        other_expert = create_rate_expert(
            prefix="deadline-other-expert",
            program=self.program,
        )
        self.client.force_authenticate(other_expert)

        response, _ = self._post()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {
                "error": "max project rates reached for this program",
                "max_project_rates": 1,
            },
        )

        self._set_deadline(self.now - timedelta(seconds=1))
        response, send_email_delay = self._post()
        self.assert_deadline_error(response)
        self.assertFalse(ProjectScore.objects.filter(user=other_expert).exists())
        send_email_delay.assert_not_called()

    def test_invalid_criteria_and_empty_payload_keep_existing_errors(self):
        self._set_deadline(self.now - timedelta(seconds=1))

        for payload in ([], [{"criterion_id": 999999, "value": "8"}]):
            with self.subTest(payload=payload):
                response, send_email_delay = self._post(payload=payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["error"], "Criteria not found")
                send_email_delay.assert_not_called()

    def test_unlinked_project_error_precedes_deadline(self):
        self._set_deadline(self.now - timedelta(seconds=1))
        unlinked_project = create_rate_project(leader=self.leader)

        response, send_email_delay = self._post(project=unlinked_project)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Project is not linked to the program")
        send_email_delay.assert_not_called()

    def test_foreign_expert_error_precedes_deadline(self):
        self._set_deadline(self.now - timedelta(seconds=1))
        outsider = create_rate_expert(prefix="deadline-outsider")
        self.client.force_authenticate(outsider)

        response, send_email_delay = self._post()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data["error"],
            "you have no permission to rate this program",
        )
        send_email_delay.assert_not_called()

    def test_non_expert_permission_error_precedes_deadline(self):
        self._set_deadline(self.now - timedelta(seconds=1))
        member = create_rate_user(prefix="deadline-member")
        self.client.force_authenticate(member)

        response, send_email_delay = self._post()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["detail"], "User is not an expert")
        self.assertFalse(ProjectScore.objects.exists())
        send_email_delay.assert_not_called()

    def test_rejection_does_not_mutate_production_evaluation_domain(self):
        self.program.is_distributed_evaluation = True
        self.program.datetime_evaluation_ends = self.now - timedelta(seconds=1)
        self.program.save(
            update_fields=[
                "is_distributed_evaluation",
                "datetime_evaluation_ends",
            ]
        )
        project_assignment = ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=self.project,
            expert=self.expert.expert,
        )
        manager = create_user(prefix="deadline-manager")
        application = Application.objects.create(
            program=self.program,
            user=self.leader,
            created_by=self.leader,
            project=self.project,
        )
        submission = Submission.objects.create(
            application=application,
            program=self.program,
            submitted_by=self.leader,
            title="Existing production submission",
        )
        submission_assignment = SubmissionExpertAssignment.objects.create(
            submission=submission,
            expert=self.expert.expert,
            assigned_by=manager,
        )
        evaluation = Evaluation.objects.create(
            submission=submission,
            expert=self.expert.expert,
        )
        evaluation_score = EvaluationScore.objects.create(
            evaluation=evaluation,
            criterion=self.criteria,
            value=Decimal("5"),
        )
        tracked = (
            self.project,
            self.program_link,
            project_assignment,
            application,
            submission,
            submission_assignment,
            evaluation,
            evaluation_score,
        )
        before = [self._row(instance) for instance in tracked]

        response, send_email_delay = self._post()

        self.assert_deadline_error(response)
        self.assertEqual([self._row(instance) for instance in tracked], before)
        self.assertFalse(ProjectScore.objects.exists())
        send_email_delay.assert_not_called()

    def test_rejection_does_not_change_analytics_read_contracts(self):
        self.program.is_distributed_evaluation = True
        self.program.datetime_evaluation_ends = self.now - timedelta(seconds=1)
        self.program.save(
            update_fields=[
                "is_distributed_evaluation",
                "datetime_evaluation_ends",
            ]
        )
        manager = create_rate_user(prefix="deadline-analytics-manager")
        self.program.managers.add(manager)
        create_program_member(self.program, user=self.leader, project=self.project)
        self.program_link.submitted = True
        self.program_link.datetime_submitted = self.now - timedelta(hours=1)
        self.program_link.save(update_fields=["submitted", "datetime_submitted"])
        assignment = ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=self.project,
            expert=self.expert.expert,
        )
        manager_client = APIClient()
        manager_client.force_authenticate(manager)
        urls = (
            reverse(
                "partner_programs:project-analytics",
                kwargs={"program_id": self.program.pk},
            ),
            reverse(
                "partner_programs:project-analytics-assignments",
                kwargs={"program_id": self.program.pk},
            ),
            reverse(
                "partner_programs:project-analytics-assignment-scores",
                kwargs={
                    "program_id": self.program.pk,
                    "assignment_id": assignment.pk,
                },
            ),
            reverse(
                "partner_programs:project-analytics-participants-without-team",
                kwargs={"program_id": self.program.pk},
            ),
            reverse(
                "partner_programs:project-analytics-projects-awaiting-evaluation",
                kwargs={"program_id": self.program.pk},
            ),
            reverse(
                "partner_programs:project-analytics-projects-not-submitted",
                kwargs={"program_id": self.program.pk},
            ),
        )

        with patch("django.utils.timezone.now", return_value=self.now):
            before = self._responses(manager_client, urls)
            response, send_email_delay = self._post()
            cache.clear()
            after = self._responses(manager_client, urls)

        self.assert_deadline_error(response)
        self.assertEqual(after, before)
        self.assertIn("cases", before[0][1])
        send_email_delay.assert_not_called()

    @staticmethod
    def _row(instance):
        return type(instance).objects.filter(pk=instance.pk).values().get()

    def _responses(self, client, urls):
        responses = []
        for url in urls:
            response = client.get(url)
            self.assertEqual(response.status_code, 200, response.data)
            responses.append((response.status_code, response.json()))
        return responses
