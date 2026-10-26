import copy
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings

from partner_programs.models import PartnerProgram, PartnerProgramField
from partner_programs.services import solution_case_actions as actions
from partner_programs.solution_models import SolutionAdministrativeChange
from partner_programs.tests.helpers import create_user
from partner_programs.tests.test_solution_case_actions import CaseFixture, FAST_HASHERS
from partner_programs.tests.test_solution_forms import call
from project_rates.models import ExpertCaseScope
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore
from project_rates.tests.helpers import create_rate_criteria, create_rate_expert


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionAdministrativeHistoryTests(CaseFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.history = (
            f"/programs/{self.program.pk}/management/solutions/"
            f"{self.solution.pk}/history/"
        )

    def get_history(
        self, path=None, actor=None, query=None, schema="SolutionAdminChangePage"
    ):
        return self.wire(
            call(actor or self.manager, "get", path or self.history, query), schema=schema
        )

    def effects(self):
        self.program.required_evaluators = 3
        self.program.save()
        self.assertEqual(self.submit().status_code, 200)
        self.rated = create_rate_expert(program=self.program)
        self.pending = create_rate_expert(program=self.program)
        self.compatible = create_rate_expert(program=self.program)
        self.assignments = []
        for expert in [self.rated, self.pending, self.compatible]:
            self.assignments.append(
                SolutionExpertAssignment.objects.create(
                    partner_program=self.program,
                    solution=self.solution,
                    expert=expert.expert,
                )
            )
        for expert in [self.rated, self.pending]:
            ExpertCaseScope.objects.create(
                partner_program=self.program,
                expert=expert.expert,
                all_cases=False,
                case_names=["Задача 1"],
            )
        self.criterion = create_rate_criteria(self.program, min_value=0, max_value=10)
        self.score = SolutionScore.objects.create(
            solution=self.solution, criteria=self.criterion, user=self.rated, value="0"
        )

    def test_submitted_change_retains_original_materials_scores_and_rated_assignments(
        self,
    ):
        self.effects()
        before = self.saved()
        original = copy.deepcopy(self.solution.submission_snapshot)
        preview = self.wire(self.preview())
        self.assertTrue(preview["is_submitted"])
        self.assertEqual(preview["removed_assignments_count"], 1)
        self.assertEqual(preview["score_count"], 1)
        self.assertEqual(self.saved(), before)
        self.assertEqual(SolutionAdministrativeChange.objects.count(), 0)
        command = dict(case_name=self.target, preview_token=preview["preview_token"])
        receipt = self.wire(self.apply(command), schema="MutationReceipt")
        self.solution.refresh_from_db()
        expected = copy.deepcopy(original)
        for answer in expected["answers"]:
            if answer["field_id"] == preview["case_field_id"]:
                answer["value"] = self.target
        self.assertEqual(self.solution.submission_snapshot, expected)
        self.assertEqual(self.solution.status, "submitted")
        self.assertEqual(
            self.solution.submitted_at, before["solution"][0]["submitted_at"]
        )
        self.assertEqual(
            receipt["solution_version"], before["solution"][0]["version"] + 1
        )
        self.assertEqual(self.saved()["scores"], before["scores"])
        self.assertEqual(self.saved()["members"], before["members"])
        self.assertEqual(
            set(self.solution.expert_assignments.values_list("pk", flat=True)),
            {self.assignments[0].pk, self.assignments[2].pk},
        )
        journal = self.solution.administrative_changes.get()
        self.assertEqual(journal.before_snapshot, original)
        self.assertEqual(journal.after_snapshot, expected)
        self.assertEqual(journal.removed_assignment_ids, [self.assignments[1].pk])
        self.assertEqual(journal.actor, self.manager)
        self.assertEqual(journal.before_version + 1, journal.after_version)
        self.assertEqual(journal.case_name, self.target)
        self.assertEqual(
            self.wire(self.apply(command), 409)["code"], "solution_action_conflict"
        )
        self.assertEqual(self.solution.administrative_changes.count(), 1)

    def test_history_lists_and_reads_exact_saved_revisions_and_safe_references(self):
        self.effects()
        self.wire(self.apply(self.command_case()), schema="MutationReceipt")
        first = self.solution.administrative_changes.get()
        first_snapshot = copy.deepcopy(first.after_snapshot)
        self.wire(self.apply(self.command_case("Задача 1")), schema="MutationReceipt")
        latest = self.solution.administrative_changes.first()
        self.assertEqual(latest.before_snapshot, first_snapshot)
        listing = self.get_history(query=dict(limit=1, offset=0))
        self.assertEqual(listing["count"], 2)
        self.assertEqual(listing["results"][0]["id"], latest.pk)
        self.assertTrue(listing["results"][0]["was_submitted"])
        old_page = self.get_history(query=dict(limit=1, offset=1))
        self.assertEqual(old_page["results"][0]["id"], first.pk)
        self.assertEqual(self.get_history(query=dict(offset=50))["results"], [])
        detail = self.get_history(
            self.history + str(first.pk) + "/", schema="SolutionAdminChangeDetail"
        )
        self.assertEqual(detail["before_snapshot"], first.before_snapshot)
        self.assertEqual(detail["after_snapshot"], first.after_snapshot)
        self.assertEqual(detail["change"]["application"]["solution_id"], self.solution.pk)
        self.assertEqual(detail["change"]["application"]["program_id"], self.program.pk)
        self.assertEqual(detail["change"]["actor"]["id"], self.manager.pk)
        self.assertNotIn("email", detail["change"]["actor"])

    def test_draft_case_change_also_records_history_without_artificial_submission(self):
        self.wire(self.apply(self.command_case()), schema="MutationReceipt")
        change = self.solution.administrative_changes.get()
        self.assertFalse(change.was_submitted)
        self.assertIsNone(change.before_snapshot)
        self.assertIsNone(change.after_snapshot)
        self.assertEqual(change.previous_case, "Задача 1")
        self.assertEqual(change.case_name, self.target)
        detail = self.get_history(
            self.history + str(change.pk) + "/", schema="SolutionAdminChangeDetail"
        )
        self.assertIsNone(detail["before_snapshot"])
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.status, "draft")

    def test_ordinary_writers_remain_frozen_after_privileged_change(self):
        self.assertEqual(self.submit().status_code, 200)
        original = self.saved()
        self.wire(self.apply(self.command_case()), schema="MutationReceipt")
        current = self.saved()
        response = self.save_answers(
            [{"field_id": self.fields["select"]["id"], "value": "Задача 1"}]
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "team_frozen")
        self.solution.submission_snapshot = original["solution"][0]["submission_snapshot"]
        with self.assertRaises(ValidationError), transaction.atomic():
            self.solution.save()
        self.assertEqual(self.saved(), current)

    def test_journal_failure_rolls_back_case_snapshot_version_and_assignment_removal(
        self,
    ):
        self.effects()
        command = self.command_case()
        before = self.saved()
        with patch.object(
            SolutionAdministrativeChange.objects,
            "create",
            side_effect=RuntimeError("journal unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                actions.apply(self.program.pk, self.solution.pk, self.manager, command)
        self.assertEqual(self.saved(), before)
        self.assertEqual(SolutionAdministrativeChange.objects.count(), 0)

    def test_changed_score_value_or_scope_invalidates_confirmation(self):
        self.effects()
        command = self.command_case()
        self.score.value = "7"
        self.score.save()
        before = self.saved()
        self.assertEqual(
            self.wire(self.apply(command), 409)["code"], "solution_action_conflict"
        )
        self.assertEqual(self.saved(), before)
        command = self.command_case()
        ExpertCaseScope.objects.filter(expert=self.pending.expert).update(all_cases=True)
        self.assertEqual(
            self.wire(self.apply(command), 409)["code"], "solution_action_conflict"
        )
        self.assertEqual(self.wire(self.preview())["removed_assignments_count"], 0)
        self.assertEqual(self.solution.administrative_changes.count(), 0)

    def test_history_is_private_and_has_no_write_route(self):
        self.wire(self.apply(self.command_case()), schema="MutationReceipt")
        change = self.solution.administrative_changes.get()
        detail = self.history + str(change.pk) + "/"
        for actor in [
            None,
            self.captain,
            create_user(),
            create_rate_expert(program=self.program),
        ]:
            status = 401 if actor is None else 403
            for path in [self.history, detail]:
                self.wire(call(actor, "get", path), status)
        for method in ["post", "patch", "delete"]:
            self.assertEqual(call(self.manager, method, detail, {}).status_code, 405)
        self.assertEqual(self.solution.administrative_changes.count(), 1)

    def test_history_rejects_foreign_change_unsafe_ids_and_unknown_queries(self):
        self.wire(self.apply(self.command_case()), schema="MutationReceipt")
        change = self.solution.administrative_changes.get()
        for suffix in [str(change.pk + 100), "0", str(2**53)]:
            self.wire(call(self.manager, "get", self.history + suffix + "/"), 404)
        for query in [dict(limit=0), dict(limit=101), dict(offset=-1), dict(all=True)]:
            self.wire(call(self.manager, "get", self.history, query), 400)
        self.wire(
            call(
                self.manager, "get", self.history + str(change.pk) + "/", dict(all=True)
            ),
            400,
        )
        foreign_path = self.history.replace(
            f"/solutions/{self.solution.pk}/", f"/solutions/{self.solution.pk + 100}/"
        )
        self.wire(call(self.manager, "get", foreign_path), 404)

    def test_history_does_not_depend_on_current_form_deadlines_or_creation_flag(self):
        self.wire(self.apply(self.command_case()), schema="MutationReceipt")
        # Historical/configuration drift must not hide already recorded evidence.
        # The ordinary template writer correctly forbids clearing it after answers.
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_template=None, solution_creation_enabled=False
        )
        self.assertEqual(self.get_history()["count"], 1)

    def test_history_cannot_be_rewritten_or_deleted_by_model_or_admin(self):
        from django.contrib import admin
        from partner_programs.solution_admin import SolutionAdministrativeChangeAdmin

        self.wire(self.apply(self.command_case()), schema="MutationReceipt")
        change = self.solution.administrative_changes.get()
        change.case_name = "Подмена истории"
        with self.assertRaises(ValidationError):
            change.save()
        with self.assertRaises(ValidationError):
            change.delete()
        with self.assertRaises(ProtectedError), transaction.atomic():
            SolutionAdministrativeChange.objects.filter(pk=change.pk).delete()
        model_admin = SolutionAdministrativeChangeAdmin(
            SolutionAdministrativeChange, admin.site
        )
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None, change))
        self.assertFalse(model_admin.has_delete_permission(None, change))
        change.refresh_from_db()
        self.assertEqual(change.case_name, self.target)

    def test_submitted_snapshot_uses_original_case_definition_after_current_form_changes(
        self,
    ):
        self.assertEqual(self.submit().status_code, 200)
        self.solution.refresh_from_db()
        original = copy.deepcopy(self.solution.submission_snapshot)
        PartnerProgramField.objects.filter(pk=self.fields["select"]["id"]).update(
            label="Новая подпись", position=30
        )
        self.wire(self.apply(self.command_case()), schema="MutationReceipt")
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.submission_snapshot["form"], original["form"])
        self.assertEqual(
            self.solution.submission_snapshot["members"], original["members"]
        )
        self.assertEqual(
            self.solution.administrative_changes.get().before_snapshot, original
        )
