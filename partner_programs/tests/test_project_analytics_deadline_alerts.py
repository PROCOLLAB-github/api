from datetime import timedelta

from django.test import TestCase

from partner_programs.tests.test_project_assignment_analytics_api import (
    NOW,
    ProjectAssignmentAnalyticsFixture,
)
from partner_programs.models import PartnerProgramProject
from partner_programs.tests.helpers import create_partner_program
from project_rates.tests.helpers import create_rate_expert
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore


class ProjectDeadlineAlertTests(ProjectAssignmentAnalyticsFixture, TestCase):
    def test_evaluation_deadline_window_and_boundaries(self):
        cases = (
            (timedelta(days=5, seconds=1), 100, None),
            (timedelta(days=5), 0, "warning"),
            (timedelta(days=5, seconds=-1), 49, "warning"),
            (timedelta(days=1), 1, "warning"),
            (timedelta(seconds=1), 1, "warning"),
            (timedelta(0), 0, "critical"),
            (timedelta(seconds=-1), 0, "critical"),
            (timedelta(days=-10), 100, "critical"),
        )
        for remaining, hours, severity in cases:
            with self.subTest(remaining=remaining, hours=hours):
                self.program.datetime_evaluation_ends = NOW + remaining
                self.program.save(update_fields=["datetime_evaluation_ends"])
                ProjectExpertAssignment.objects.all().delete()
                self.assignment(hours=hours)
                delayed = self.get(self.overview_url)["attention"]["delayed_experts"]
                self.assertEqual(delayed["total"], int(severity is not None))
                if severity is not None:
                    item = delayed["items"][0]
                    self.assertEqual(item["severity"], severity)
                    self.assertEqual(item["assignments_total"], 1)
                    self.assertEqual(item["pending"], 1)
                    self.assertEqual(item["completed"], 0)
                    self.assertEqual(item["overdue_24h"], int(hours >= 24))
                    self.assertEqual(item["overdue_48h"], int(hours >= 48))
                    self.assertEqual(item["oldest_waiting_seconds"], hours * 3600)

    def test_old_24h_and_48h_thresholds_do_not_trigger_before_deadline_window(self):
        self.program.datetime_evaluation_ends = NOW + timedelta(days=6)
        self.program.save(update_fields=["datetime_evaluation_ends"])
        self.assignment(hours=25)
        self.assignment(hours=25)
        self.assignment(hours=100)
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"],
            {"total": 0, "items": []},
        )

    def test_missing_evaluation_deadline_does_not_use_other_program_dates(self):
        self.program.datetime_evaluation_ends = None
        self.program.datetime_finished = NOW
        self.program.datetime_registration_ends = NOW
        self.program.datetime_project_submission_ends = NOW
        self.program.save()
        self.assignment(hours=100)
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"],
            {"total": 0, "items": []},
        )

    def test_completing_scores_removes_signal_and_moving_deadline_recalculates_it(self):
        assignment = self.assignment(hours=0)
        self.score(assignment, 1)
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"]["total"], 1
        )
        self.program.datetime_evaluation_ends = NOW + timedelta(days=6)
        self.program.save(update_fields=["datetime_evaluation_ends"])
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"]["total"], 0
        )
        self.program.datetime_evaluation_ends = NOW
        self.program.save(update_fields=["datetime_evaluation_ends"])
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"]["items"][0][
                "severity"
            ],
            "critical",
        )
        # Saving the program also ensures its default Comment criterion exists.
        for criterion in Criteria.objects.filter(partner_program=self.program):
            ProjectScore.objects.get_or_create(
                criteria=criterion,
                project_id=assignment.project_id,
                user_id=assignment.expert.user_id,
                defaults={"value": "0"},
            )
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"]["total"], 0
        )

    def test_completed_and_not_ready_do_not_trigger_deadline_signal(self):
        self.score(self.assignment(hours=100))
        self.assignment(hours=100, submitted=False)
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"],
            {"total": 0, "items": []},
        )

    def test_other_program_assignments_do_not_leak_into_deadline_signal_or_list(self):
        other = create_partner_program(is_distributed_evaluation=True)
        self.expert.expert.programs.add(other)
        self.assignment(hours=100, program=other)
        self.assertEqual(self.get(), [])
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"]["total"], 0
        )

    def test_delayed_experts_sort_by_known_waiting_then_duration_and_id(self):
        warning = create_rate_expert(program=self.program)
        for _ in range(2):
            self.assignment(expert=warning, hours=25)
        self.assignment(hours=49)
        oldest = create_rate_expert(program=self.program)
        self.assignment(expert=oldest, hours=60)
        tied = create_rate_expert(program=self.program)
        self.assignment(expert=tied, hours=60)
        unknown = create_rate_expert(program=self.program)
        unknown_assignment = self.assignment(expert=unknown, hours=100)
        PartnerProgramProject.objects.filter(project=unknown_assignment.project).update(
            datetime_submitted=None
        )
        items = self.get(self.overview_url)["attention"]["delayed_experts"]["items"]
        self.assertEqual(
            [item["user_id"] for item in items],
            [oldest.pk, tied.pk, self.expert.pk, warning.pk, unknown.pk],
        )
        self.assertTrue(all(item["severity"] == "warning" for item in items))
