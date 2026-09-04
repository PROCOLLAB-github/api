from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject
from partner_programs.services.assignment_analytics import build_assignments
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_user,
)
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import create_rate_expert

NOW = datetime(2026, 9, 5, 12, tzinfo=datetime_timezone.utc)


class AssignmentAnalyticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = create_user(prefix="assignment-manager")
        cls.program = create_partner_program(
            is_distributed_evaluation=True, max_project_rates=3
        )
        cls.program.managers.add(cls.manager)
        cls.expert = create_rate_expert(program=cls.program)
        # Program creation adds a Comment criterion; isolate exactly three here.
        Criteria.objects.filter(partner_program=cls.program).delete()
        cls.criteria = [
            Criteria.objects.create(
                partner_program=cls.program,
                name=f"Criterion {index}",
                description="Description",
                type="int",
                min_value=0,
                max_value=10,
            )
            for index in range(3)
        ]

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.url = reverse(
            "partner_programs:manager-overview-assignments",
            kwargs={"pk": self.program.pk},
        )
        self.overview_url = reverse(
            "partner_programs:manager-overview", kwargs={"pk": self.program.pk}
        )

    def assignment(self, *, submitted=True, hours=25, expert=None, program=None):
        program = program or self.program
        expert = expert or self.expert
        link = create_program_project(program, submitted=submitted)
        assigned = ProjectExpertAssignment.objects.create(
            partner_program=program, project=link.project, expert=expert.expert
        )
        timestamp = NOW - timedelta(hours=hours)
        ProjectExpertAssignment.objects.filter(pk=assigned.pk).update(
            datetime_created=timestamp
        )
        PartnerProgramProject.objects.filter(pk=link.pk).update(
            datetime_submitted=timestamp if submitted else None
        )
        return assigned

    def score(self, assignment, count=3):
        for criterion in self.criteria[:count]:
            ProjectScore.objects.get_or_create(
                criteria=criterion,
                project_id=assignment.project_id,
                user_id=assignment.expert.user_id,
                defaults={"value": "0"},
            )

    def scores_url(self, assignment, *, program=None):
        return reverse(
            "partner_programs:manager-overview-assignment-scores",
            kwargs={
                "pk": (program or self.program).pk,
                "assignment_id": assignment.pk,
            },
        )

    def get(self, url=None, **params):
        with patch("django.utils.timezone.now", return_value=NOW):
            response = self.client.get(url or self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_zero_one_two_three_criteria_scores_map_to_statuses(self):
        assignment = self.assignment()
        for count, expected in enumerate(
            ("pending", "in_progress", "in_progress", "completed")
        ):
            with self.subTest(count=count):
                self.score(assignment, count)
                item = self.get()[0]
                self.assertEqual(item["status"], expected)
                self.assertEqual(item["criteria_total"], 3)
                self.assertEqual(item["criteria_scored"], count)

    def test_zero_criteria_is_pending_not_completed(self):
        Criteria.objects.filter(partner_program=self.program).delete()
        self.assignment()
        item = self.get()[0]
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["criteria_total"], 0)

    def test_unsubmitted_even_with_scores_is_not_ready(self):
        assignment = self.assignment(submitted=False)
        self.score(assignment)
        item = self.get()[0]
        self.assertEqual(item["status"], "not_ready")
        self.assertFalse(item["project_submitted"])
        for field in ("project_submitted_at", "waiting_since", "waiting_seconds"):
            self.assertIsNone(item[field])

    def test_duplicate_criterion_score_is_rejected_and_cannot_inflate_progress(self):
        assignment = self.assignment()
        self.score(assignment, 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProjectScore.objects.create(
                criteria=self.criteria[0],
                project=assignment.project,
                user=self.expert,
                value="8",
            )
        self.assertEqual(self.get()[0]["criteria_scored"], 1)

    def test_unrelated_program_user_and_project_scores_are_ignored(self):
        assignment = self.assignment()
        other = self.assignment()
        self.score(other)
        other_expert = create_rate_expert(program=self.program)
        other_criterion = Criteria.objects.create(
            partner_program=create_partner_program(), name="Other", type="int"
        )
        ProjectScore.objects.create(
            criteria=other_criterion,
            user=self.expert,
            project=assignment.project,
            value="8",
        )
        ProjectScore.objects.create(
            criteria=self.criteria[0],
            user=other_expert,
            project=assignment.project,
            value="9",
        )
        self.score(assignment, 1)
        item = self.get()[0]
        self.assertEqual(item["criteria_scored"], 1)
        self.assertEqual(item["status"], "in_progress")
        scores = self.get(self.scores_url(assignment))["scores"]
        self.assertEqual([item["value"] for item in scores], ["0", None, None])

    def test_summary_preserves_names_and_counts_only_complete_assignments(self):
        self.assignment(submitted=False)
        self.assignment()
        self.score(self.assignment(), 1)
        self.score(self.assignment())
        counts = self.get(self.overview_url)["evaluation_status"]["assignments"]
        self.assertEqual(counts, {"total": 4, "pending": 3, "evaluated": 1})
        self.assertEqual(counts["total"], counts["pending"] + counts["evaluated"])

    def test_project_transitions_require_completed_experts_not_partial_scores(self):
        first = self.assignment()
        assignments = [first]
        for _ in range(2):
            expert = create_rate_expert(program=self.program)
            assignments.append(
                ProjectExpertAssignment.objects.create(
                    partner_program=self.program,
                    project=first.project,
                    expert=expert.expert,
                )
            )
        for assignment in assignments:
            self.score(assignment, 1)
        for completed, expected in enumerate(
            (
                "awaiting_evaluation",
                "partially_evaluated",
                "partially_evaluated",
                "evaluated",
            )
        ):
            with self.subTest(completed=completed):
                for assignment in assignments[:completed]:
                    self.score(assignment)
                data = self.get(self.overview_url)
                statuses = data["evaluation_status"]["projects"]
                self.assertEqual(statuses[expected], 1)
                self.assertEqual(sum(statuses.values()), 2)  # submitted + one status
                self.assertEqual(
                    data["solution_funnel"]["evaluated"], int(completed == 3)
                )

    def test_submitted_project_without_assignments_is_awaiting(self):
        create_program_project(self.program, submitted=True)
        data = self.get(self.overview_url)
        self.assertEqual(data["evaluation_status"]["projects"]["awaiting_evaluation"], 1)

    def test_open_mode_any_score_still_evaluates_project_without_fake_assignments(self):
        self.program.is_distributed_evaluation = False
        self.program.save(update_fields=["is_distributed_evaluation"])
        link = create_program_project(self.program, submitted=True)
        ProjectScore.objects.create(
            criteria=self.criteria[0], project=link.project, user=self.expert, value="1"
        )
        data = self.get(self.overview_url)
        self.assertEqual(data["evaluation_status"]["projects"]["evaluated"], 1)
        self.assertEqual(data["evaluation_status"]["assignments"]["total"], 0)
        self.assertEqual(self.get(), [])

    def test_waiting_starts_at_later_of_assignment_and_submission(self):
        assignment = self.assignment()
        for assigned_hours, submitted_hours in ((4, 2), (1, 4)):
            with self.subTest(assigned=assigned_hours, submitted=submitted_hours):
                assigned_at = NOW - timedelta(hours=assigned_hours)
                submitted_at = NOW - timedelta(hours=submitted_hours)
                ProjectExpertAssignment.objects.filter(pk=assignment.pk).update(
                    datetime_created=assigned_at
                )
                PartnerProgramProject.objects.filter(project=assignment.project).update(
                    datetime_submitted=submitted_at
                )
                with patch("django.utils.timezone.now", return_value=NOW):
                    item = build_assignments(self.program.pk)[0]
                self.assertEqual(item["waiting_since"], max(assigned_at, submitted_at))
                self.assertEqual(
                    item["waiting_seconds"], min(assigned_hours, submitted_hours) * 3600
                )

    def test_completed_assignment_has_no_waiting(self):
        self.score(self.assignment(hours=100))
        item = self.get()[0]
        self.assertIsNone(item["waiting_since"])
        self.assertIsNone(item["waiting_seconds"])

    def test_missing_legacy_submission_timestamp_does_not_invent_waiting(self):
        assignment = self.assignment(hours=100)
        PartnerProgramProject.objects.filter(project=assignment.project).update(
            datetime_submitted=None
        )
        item = self.get()[0]
        self.assertEqual(item["status"], "pending")
        self.assertTrue(item["project_submitted"])
        self.assertIsNone(item["waiting_seconds"])
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"]["total"], 0
        )

    def test_future_waiting_is_clamped_to_zero_and_not_delayed(self):
        self.assignment(hours=-5)
        self.assertEqual(self.get()[0]["waiting_seconds"], 0)
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"]["total"], 0
        )

    def test_sla_thresholds_and_boundaries(self):
        cases = (
            (1, 23, None),
            (2, 23, None),
            (2, 25, "warning"),
            (1, 49, "critical"),
            (1, 24, None),
            (2, 24, "warning"),
            (1, 48, "critical"),
        )
        for count, hours, severity in cases:
            with self.subTest(count=count, hours=hours):
                ProjectExpertAssignment.objects.all().delete()
                for _ in range(count):
                    self.assignment(hours=hours)
                delayed = self.get(self.overview_url)["attention"]["delayed_experts"]
                self.assertEqual(delayed["total"], int(severity is not None))
                if severity is not None:
                    item = delayed["items"][0]
                    self.assertEqual(item["severity"], severity)
                    self.assertEqual(item["assignments_total"], count)
                    self.assertEqual(item["pending"], count)
                    self.assertEqual(item["completed"], 0)
                    self.assertEqual(item["overdue_24h"], count)
                    self.assertEqual(item["overdue_48h"], count if hours >= 48 else 0)
                    self.assertEqual(item["oldest_waiting_seconds"], hours * 3600)

    def test_completed_and_not_ready_do_not_trigger_sla(self):
        self.score(self.assignment(hours=100))
        self.assignment(hours=100, submitted=False)
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"],
            {"total": 0, "items": []},
        )

    def test_delayed_expert_totals_include_completed_and_not_ready(self):
        self.score(self.assignment(hours=100))
        self.assignment(hours=100, submitted=False)
        self.score(self.assignment(hours=49), 1)
        item = self.get(self.overview_url)["attention"]["delayed_experts"]["items"][0]
        self.assertEqual(item["assignments_total"], 3)
        self.assertEqual(item["completed"], 1)
        self.assertEqual(item["pending"], 2)
        self.assertEqual(item["overdue_48h"], 1)
        self.assertEqual(item["oldest_waiting_seconds"], 49 * 3600)

    def test_other_program_assignments_do_not_leak_into_sla_or_list(self):
        other = create_partner_program(is_distributed_evaluation=True)
        self.expert.expert.programs.add(other)
        self.assignment(hours=100, program=other)
        self.assertEqual(self.get(), [])
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"]["total"], 0
        )

    def test_open_mode_never_returns_delayed_experts(self):
        self.assignment(hours=100)
        self.program.is_distributed_evaluation = False
        self.program.save(update_fields=["is_distributed_evaluation"])
        self.assertEqual(
            self.get(self.overview_url)["attention"]["delayed_experts"],
            {"total": 0, "items": []},
        )
        self.assertEqual(len(self.get()), 1)  # Real assignments are still available.

    def test_delayed_experts_sort_by_severity_wait_and_id(self):
        warning = create_rate_expert(program=self.program)
        for _ in range(2):
            self.assignment(expert=warning, hours=25)
        self.assignment(hours=49)
        oldest = create_rate_expert(program=self.program)
        self.assignment(expert=oldest, hours=60)
        items = self.get(self.overview_url)["attention"]["delayed_experts"]["items"]
        self.assertEqual(
            [item["user_id"] for item in items], [oldest.pk, self.expert.pk, warning.pk]
        )

    def test_manager_staff_superuser_access_to_both_endpoints(self):
        assignment = self.assignment()
        for user in (
            self.manager,
            create_user(is_staff=True),
            create_user(is_superuser=True),
        ):
            with self.subTest(user=user.pk):
                self.client.force_authenticate(user)
                self.get()
                self.get(self.scores_url(assignment))

    def test_participant_expert_and_other_manager_are_forbidden(self):
        assignment = self.assignment()
        participant = create_user()
        create_program_member(self.program, user=participant)
        other_manager = create_user()
        create_partner_program().managers.add(other_manager)
        for user in (participant, self.expert, other_manager):
            with self.subTest(user=user.pk):
                self.client.force_authenticate(user)
                for url in (self.url, self.scores_url(assignment)):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_anonymous_is_unauthorized(self):
        assignment = self.assignment()
        self.client.force_authenticate(None)
        for url in (self.url, self.scores_url(assignment)):
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_endpoints_are_read_only(self):
        assignment = self.assignment()
        for url in (self.url, self.scores_url(assignment)):
            for method in (
                self.client.post,
                self.client.patch,
                self.client.put,
                self.client.delete,
            ):
                self.assertEqual(method(url, {}, format="json").status_code, 405)

    def test_missing_program_and_assignment_are_not_found(self):
        for name, kwargs in (
            ("manager-overview-assignments", {"pk": 999999}),
            (
                "manager-overview-assignment-scores",
                {"pk": self.program.pk, "assignment_id": 999999},
            ),
        ):
            self.assertEqual(
                self.client.get(
                    reverse("partner_programs:" + name, kwargs=kwargs)
                ).status_code,
                404,
            )

    def test_other_program_assignment_is_not_found_even_for_both_programs_manager(self):
        other = create_partner_program()
        other.managers.add(self.manager)
        self.expert.expert.programs.add(other)
        assignment = self.assignment(program=other)
        self.assertEqual(self.client.get(self.scores_url(assignment)).status_code, 404)

    def test_scopes_and_default_have_stable_assignment_id_order(self):
        self.assignment(submitted=False)
        self.assignment()
        self.score(self.assignment(), 1)
        complete = self.assignment()
        self.score(complete)
        all_items = self.get()
        ids = [item["assignment_id"] for item in all_items]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(self.get(scope="all"), all_items)
        self.assertEqual(
            [item["status"] for item in self.get(scope="pending")],
            ["not_ready", "pending", "in_progress"],
        )
        self.assertEqual(
            [item["assignment_id"] for item in self.get(scope="completed")], [complete.pk]
        )

    def test_invalid_scopes_return_400(self):
        for scope in ("", "unknown", "COMPLETED", "evaluated"):
            self.assertEqual(self.client.get(self.url, {"scope": scope}).status_code, 400)

    def test_assignment_has_explicit_safe_contract(self):
        assignment = self.assignment(hours=49)
        item = self.get()[0]
        self.assertEqual(
            set(item),
            {
                "assignment_id",
                "expert",
                "project",
                "status",
                "criteria_total",
                "criteria_scored",
                "assigned_at",
                "project_submitted",
                "project_submitted_at",
                "waiting_since",
                "waiting_seconds",
            },
        )
        self.assertEqual(
            set(item["expert"]),
            {"expert_id", "user_id", "first_name", "last_name", "full_name", "avatar"},
        )
        self.assertEqual(
            item["project"],
            {"id": assignment.project_id, "name": assignment.project.name},
        )
        self.assertEqual(item["expert"]["full_name"], "Rate User")
        self.assertIsNone(item["expert"]["avatar"])
        delayed = self.get(self.overview_url)["attention"]["delayed_experts"]["items"][0]
        for payload in (item, delayed, self.get(self.scores_url(assignment))):
            self.assertNotIn("email", str(payload))
            self.assertNotIn("password", str(payload))
            self.assertNotIn("is_staff", str(payload))

    def test_avatar_is_url_and_blank_names_do_not_break_overview(self):
        self.expert.first_name = ""
        self.expert.last_name = ""
        self.expert.avatar = "https://example.test/avatar.png"
        self.expert.save(update_fields=["first_name", "last_name", "avatar"])
        self.assignment(hours=49)
        expert = self.get()[0]["expert"]
        self.assertEqual(expert["full_name"], "")
        self.assertEqual(expert["avatar"], self.expert.avatar)
        self.get(self.overview_url)

    def test_score_detail_returns_all_criteria_with_progress_and_missing_values(self):
        assignment = self.assignment()
        for count in (0, 1, 3):
            with self.subTest(count=count):
                self.score(assignment, count)
                detail = self.get(self.scores_url(assignment))
                self.assertEqual(detail["criteria_scored"], count)
                self.assertEqual(detail["criteria_total"], 3)
                scores = detail["scores"]
                self.assertEqual(
                    [item["criterion_id"] for item in scores],
                    [item.pk for item in self.criteria],
                )
                for index, item in enumerate(scores):
                    self.assertEqual(
                        set(item),
                        {
                            "criterion_id",
                            "name",
                            "description",
                            "type",
                            "min_value",
                            "max_value",
                            "value",
                            "is_scored",
                        },
                    )
                    self.assertEqual(item["is_scored"], index < count)
                    self.assertEqual(item["value"], "0" if index < count else None)
                    self.assertEqual(item["description"], "Description")
                    self.assertEqual(item["min_value"], 0)
                    self.assertEqual(item["max_value"], 10)

    def test_score_text_value_is_not_coerced_or_trimmed(self):
        criterion = self.criteria[0]
        criterion.type = "str"
        criterion.save(update_fields=["type"])
        assignment = self.assignment()
        ProjectScore.objects.create(
            criteria=criterion,
            project=assignment.project,
            user=self.expert,
            value="  text  ",
        )
        self.assertEqual(
            self.get(self.scores_url(assignment))["scores"][0]["value"], "  text  "
        )

    def test_query_counts_are_constant_for_one_and_many_assignments(self):
        first = self.assignment(hours=49)
        self.score(first, 1)
        urls = (self.url, self.overview_url, self.scores_url(first))
        counts = []
        for url in urls:
            with CaptureQueriesContext(connection) as queries:
                self.get(url)
            counts.append(len(queries))
        self.assertEqual(counts, [3, 10, 5])
        for _ in range(30):
            expert = create_rate_expert(program=self.program)
            self.score(self.assignment(expert=expert, hours=49), 1)
        for url, expected in zip(urls, counts):
            with CaptureQueriesContext(connection) as queries:
                self.get(url)
            self.assertEqual(len(queries), expected)
