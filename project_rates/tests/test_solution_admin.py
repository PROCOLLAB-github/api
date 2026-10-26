from html.parser import HTMLParser
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from partner_programs.tests.helpers import create_user
from partner_programs.models import PartnerProgram
from partner_programs.tests.test_solution_submission import SubmissionFixture
from project_rates.models import Criteria
from project_rates.solution_models import SolutionScore, SolutionExpertAssignment
from project_rates.tests.test_solution_evaluation import EvaluationFixture


class HiddenInputs(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.values = {}
        self.feed(content.decode())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("type") == "hidden" and attrs.get("name"):
            self.values[attrs["name"]] = attrs.get("value", "")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionAdminTests(EvaluationFixture, TestCase):
    def setUp(self):
        self.seed_evaluation()
        self.staff = create_user(is_staff=True, is_superuser=True, is_active=True)
        self.client.force_login(self.staff)

    def test_bulk_add_uses_real_solutions_and_preserves_atomic_validation(self):
        first, second = self.another_solution(), self.another_solution()
        url = reverse("admin:project_rates_solutionexpertassignment_add")
        response = self.client.post(
            url,
            dict(
                partner_program=self.program.pk,
                expert=self.second.expert.pk,
                solutions=[first.pk, second.pk],
                _save="save",
            ),
        )
        self.assertEqual(response.status_code, 302, response.content[:400])
        self.assertEqual(
            set(
                SolutionExpertAssignment.objects.filter(
                    expert=self.second.expert
                ).values_list("solution_id", flat=True)
            ),
            {first.pk, second.pk},
        )
        draft = self.another_solution(submitted=False)
        response = self.client.post(
            url,
            dict(
                partner_program=self.program.pk,
                expert=self.second.expert.pk,
                solutions=[self.solution.pk, draft.pk],
                _save="save",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            SolutionExpertAssignment.objects.filter(
                expert=self.second.expert, solution=self.solution
            ).exists()
        )

    def test_bulk_add_cannot_exceed_quota_or_assign_own_team(self):
        url = reverse("admin:project_rates_solutionexpertassignment_add")
        response = self.client.post(
            url,
            dict(
                partner_program=self.program.pk,
                expert=self.second.expert.pk,
                solutions=[self.solution.pk],
                _save="save",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SolutionExpertAssignment.objects.count(), 1)
        from users.models import Expert

        self.program.required_evaluators = 2
        self.program.save()
        self.captain.is_active = True
        self.captain.save(update_fields=["is_active"])
        own, _ = Expert.objects.get_or_create(user=self.captain)
        own.programs.add(self.program)
        response = self.client.post(
            url,
            dict(
                partner_program=self.program.pk,
                expert=own.pk,
                solutions=[self.solution.pk],
                _save="save",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SolutionExpertAssignment.objects.count(), 1)

    def test_admin_draft_name_edit_advances_version(self):
        draft = self.another_solution(submitted=False)
        before = draft.version
        url = reverse("admin:partner_programs_programsolution_change", args=[draft.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = HiddenInputs(response.content).values
        data.update(name="Новое название", _save="save")
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, response.content[:400])
        draft.refresh_from_db()
        self.assertEqual(draft.version, before + 1)
        self.assertEqual(draft.name, "Новое название")

    def test_partial_scores_protect_single_and_bulk_assignment_deletion(self):
        self.program.required_evaluators = 2
        self.program.save()
        removable = SolutionExpertAssignment.objects.create(
            partner_program=self.program,
            solution=self.solution,
            expert=self.second.expert,
        )
        SolutionScore.objects.create(
            solution=self.solution, user=self.expert, criteria=self.criteria[0], value="0"
        )
        response = self.client.get(
            reverse(
                "admin:project_rates_solutionexpertassignment_delete",
                args=[self.assignment.pk],
            )
        )
        self.assertEqual(response.status_code, 302)
        url = reverse("admin:project_rates_solutionexpertassignment_changelist")
        response = self.client.post(
            url,
            {
                "action": "delete_selected",
                "_selected_action": [self.assignment.pk, removable.pk],
                "post": "yes",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            SolutionExpertAssignment.objects.filter(pk=self.assignment.pk).exists()
        )
        self.assertFalse(
            SolutionExpertAssignment.objects.filter(pk=removable.pk).exists()
        )

    def test_submitted_admin_view_cannot_change_snapshot_status_or_name(self):
        url = reverse(
            "admin:partner_programs_programsolution_change", args=[self.solution.pk]
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotRegex(response.content.decode(), r'<input[^>]*\bname="name"')
        data = HiddenInputs(response.content).values
        data.update(name="Изменено", status="draft", submitted_at="", _save="save")
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, response.content[:400])
        original = self.solution.submission_snapshot
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.status, "submitted")
        self.assertEqual(self.solution.name, original["name"])
        self.assertEqual(self.solution.submission_snapshot, original)
        self.assertEqual(
            self.client.get(
                reverse(
                    "admin:partner_programs_programsolution_delete",
                    args=[self.solution.pk],
                )
            ).status_code,
            403,
        )

    def test_score_admin_validates_value_and_permanently_locks_criteria(self):
        url = reverse("admin:project_rates_solutionscore_add")
        data = dict(
            solution=self.solution.pk,
            user=self.expert.pk,
            criteria=self.criteria[0].pk,
            value="NaN",
            _save="save",
        )
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertFalse(SolutionScore.objects.exists())
        data["value"] = "0"
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, response.content[:400])
        self.assertEqual(SolutionScore.objects.get().value, "0")
        self.program.refresh_from_db()
        self.assertIsNotNone(self.program.evaluation_criteria_locked_at)

    def test_direct_score_write_rechecks_criterion_program_after_lock(self):
        other = SubmissionFixture()
        other.ready()
        self.assertEqual(other.submit().status_code, 200)
        other.solution.refresh_from_db()
        select = PartnerProgram.objects.select_for_update

        def criterion_moved_before_lock():
            Criteria.objects.filter(pk=self.criteria[0].pk).update(
                partner_program=other.program
            )
            return select()

        from django.core.exceptions import ValidationError

        with patch.object(
            PartnerProgram.objects,
            "select_for_update",
            side_effect=criterion_moved_before_lock,
        ):
            with self.assertRaises(ValidationError):
                SolutionScore.objects.create(
                    solution=other.solution,
                    user=self.expert,
                    criteria=self.criteria[0],
                    value="0",
                )
        self.assertFalse(SolutionScore.objects.exists())
        self.program.refresh_from_db()
        other.program.refresh_from_db()
        self.assertIsNone(self.program.evaluation_criteria_locked_at)
        self.assertIsNone(other.program.evaluation_criteria_locked_at)
