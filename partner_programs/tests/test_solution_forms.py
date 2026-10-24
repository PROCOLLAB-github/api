import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs import solution_forms
from partner_programs.solution_api import create_solution, solution_data
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_models import ProgramSolutionAnswer
from partner_programs.solution_schema import (
    form_data,
    template_fields,
    VALIDATION_DEFAULTS,
)
from partner_programs.tests.helpers import create_user, create_program_member
from partner_programs.tests.test_solution_foundation import solution_program


def call(actor, method, url, data=None):
    client = APIClient()
    client.force_authenticate(actor)
    return getattr(client, method)(url, {} if data is None else data, format="json")


def new_field(kind="textarea", purpose="other", **overrides):
    result = dict(
        id=None,
        type=kind,
        purpose=purpose,
        label="Новое поле",
        help_text="",
        required=False,
        position=1,
        options=[],
        validation=copy.deepcopy(VALIDATION_DEFAULTS),
    )
    result.update(overrides)
    return result


class FormFixture:
    def seed(self):
        self.program = solution_program(is_competitive=True)
        self.manager = create_user()
        self.program.managers.add(self.manager)
        self.captain = create_user()
        create_program_member(self.program, user=self.captain)
        self.solution, _ = create_solution(self.program.pk, self.captain, {})
        self.root = f"/programs/{self.program.pk}/management/solution-form/"
        self.read_root = f"/programs/{self.program.pk}/solution-form/"

    def payload(self, **overrides):
        form = form_data(self.program)
        result = dict(
            expected_revision=form["revision"],
            template=form["template"],
            fields=form["fields"],
        )
        result.update(overrides)
        return copy.deepcopy(result)

    def put(self, payload=None, actor=None):
        return call(actor or self.manager, "put", self.root, payload or self.payload())

    def answer(self, field_id, value):
        return ProgramSolutionAnswer.objects.create(
            solution=self.solution, field_id=field_id, value=value
        )

    def assert_error(self, response, code, status=409):
        self.assertEqual(response.status_code, status, response.data)
        self.assertEqual(response.data["code"], code)
        self.assertEqual(set(response.data), {"code", "detail", "errors", "meta"})


class SolutionFormTests(FormFixture, TestCase):
    def setUp(self):
        self.seed()

    def test_templates_match_contract_and_are_independent_copies(self):
        response = call(self.manager, "get", "/solution-form-templates/")
        self.assertEqual(response.status_code, 200)
        spec = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text(encoding="utf-8")
        )
        expected = spec["paths"]["/solution-form-templates/"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["examples"]["templates"]["value"]
        self.assertEqual(response.data, expected)
        response.data["results"][0]["fields"][0]["options"].append("Изменение")
        self.assertEqual(template_fields()["results"][0]["fields"][0]["options"], [])
        self.assertEqual(
            call(self.manager, "get", "/solution-form-templates/?unknown=1").status_code,
            400,
        )
        self.assertEqual(APIClient().get("/solution-form-templates/").status_code, 401)

    def test_reads_and_management_match_openapi_with_program_scoped_permissions(self):
        outsider = create_user()
        other_manager = create_user()
        other_program = solution_program()
        other_program.managers.add(other_manager)
        for actor in (outsider, other_manager):
            self.assert_error(
                call(actor, "get", self.read_root), "permission_denied", 403
            )
            self.assert_error(call(actor, "get", self.root), "permission_denied", 403)
        self.assertEqual(call(self.captain, "get", self.read_root).status_code, 200)
        self.assert_error(call(self.captain, "get", self.root), "permission_denied", 403)
        staff = create_user(is_staff=True)
        self.assertEqual(call(staff, "get", self.root).status_code, 200)
        spec = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text(encoding="utf-8")
        )
        from jsonschema import Draft202012Validator

        for schema, url in (("Form", self.read_root), ("FormManagement", self.root)):
            Draft202012Validator(
                {
                    "components": spec["components"],
                    "$ref": f"#/components/schemas/{schema}",
                }
            ).validate(call(self.manager, "get", url).data)

    def test_before_configuration_does_not_choose_or_copy_template_automatically(self):
        self.program.fields.all().delete()
        self.program.solution_template = None
        self.program.save()
        response = call(self.captain, "get", self.read_root)
        self.assertIsNone(response.data["template"])
        self.assertEqual(response.data["fields"], [])
        self.assertFalse(response.data["is_configured"])

    def test_save_each_template_copies_definitions_and_normalizes_order(self):
        for template in template_fields()["results"]:
            with self.subTest(template=template["key"]):
                rows = copy.deepcopy(template["fields"])
                rows[0]["options"] = ["Трек A | B", "Трек C"]
                for index, row in enumerate(rows):
                    row["position"] = index * 10
                response = self.put(
                    self.payload(template=template["key"], fields=list(reversed(rows)))
                )
                self.assertEqual(response.status_code, 200, response.data)
                form = response.data["form"]
                self.assertEqual(form["template"], template["key"])
                self.assertTrue(form["is_configured"])
                self.assertEqual(
                    [field["position"] for field in form["fields"]],
                    list(range(len(rows))),
                )
                self.assertTrue(all(field["id"] for field in form["fields"]))
                self.assertEqual(form["fields"][0]["options"], ["Трек A | B", "Трек C"])
                self.assertEqual(
                    self.program.fields.get(name="case").get_options_list(),
                    ["Трек A | B", "Трек C"],
                )
                self.program.refresh_from_db()

    def test_stale_form_does_not_write_any_part(self):
        payload = self.payload()
        first = self.put(
            {**payload, "fields": [{**payload["fields"][0], "label": "Изменено"}]}
        )
        self.assertEqual(first.status_code, 200)
        self.assert_error(self.put(payload), "form_revision_conflict")
        self.assertEqual(self.program.fields.get().label, "Изменено")

    def test_mode_rollback_blocks_put_but_allows_read(self):
        payload = self.payload()
        self.program.solution_storage_mode = "legacy_project"
        self.program.save()
        self.assert_error(self.put(payload), "solution_mode_unavailable")
        self.assertEqual(call(self.captain, "get", self.read_root).status_code, 200)

    def test_strict_types_unknown_properties_and_invalid_validation_ranges_are_atomic(
        self,
    ):
        invalid = [
            {"expected_revision": "bad"},
            {"team_id": 1},
            {"fields": [{**self.payload()["fields"][0], "required": "true"}]},
            {"fields": [{**self.payload()["fields"][0], "id": True}]},
            {"fields": [{**self.payload()["fields"][0], "position": -1}]},
            {
                "fields": [
                    self.payload()["fields"][0],
                    new_field(
                        validation={
                            **VALIDATION_DEFAULTS,
                            "min_length": 5,
                            "max_length": 2,
                        }
                    ),
                ]
            },
            {
                "fields": [
                    self.payload()["fields"][0],
                    new_field(
                        "number", validation={**VALIDATION_DEFAULTS, "minimum": True}
                    ),
                ]
            },
            {
                "fields": [
                    self.payload()["fields"][0],
                    new_field(
                        "number", validation={**VALIDATION_DEFAULTS, "max_length": 5}
                    ),
                ]
            },
            {
                "fields": [
                    self.payload()["fields"][0],
                    new_field(
                        "file",
                        validation={
                            **VALIDATION_DEFAULTS,
                            "max_file_size_bytes": 104857601,
                        },
                    ),
                ]
            },
            {
                "fields": [
                    self.payload()["fields"][0],
                    new_field(
                        "file",
                        validation={**VALIDATION_DEFAULTS, "allowed_extensions": ["PDF"]},
                    ),
                ]
            },
        ]
        before = self.payload()
        for changes in invalid:
            with self.subTest(changes=changes):
                self.assert_error(
                    self.put({**before, **changes}), "validation_error", 400
                )
                self.assertEqual(self.payload(), before)

    def test_duplicate_unknown_field_ids_and_positions_rejected(self):
        case = self.payload()["fields"][0]
        other = solution_program().fields.get()
        for rows in (
            [case, case],
            [{**case, "id": other.pk}],
            [case, new_field(position=0)],
        ):
            self.assert_error(
                self.put(self.payload(fields=rows)), "validation_error", 400
            )

    def test_semantic_purposes_case_options_and_new_radio_rules(self):
        case = self.payload()["fields"][0]
        for rows in (
            [],
            [{**case, "type": "text", "options": []}],
            [{**case, "required": False}],
            [{**case, "options": []}],
            [{**case, "options": [" A ", "a"]}],
            [{**case, "options": ["  "]}],
            [case, new_field("url", "presentation")],
            [case, new_field("file", "repository")],
            [case, new_field("select", "case", options=["B"])],
            [case, new_field("radio", options=["A"])],
        ):
            with self.subTest(rows=rows):
                self.assert_error(
                    self.put(self.payload(fields=rows)), "validation_error", 400
                )

    def test_used_field_cannot_be_removed_retyped_or_repurposed(self):
        response = self.put(self.payload(fields=[*self.payload()["fields"], new_field()]))
        target = response.data["form"]["fields"][1]
        self.answer(target["id"], "Текст")
        for fields in (
            [self.payload()["fields"][0]],
            [self.payload()["fields"][0], {**target, "type": "text"}],
            [self.payload()["fields"][0], {**target, "purpose": "run_instructions"}],
        ):
            self.assert_error(self.put(self.payload(fields=fields)), "field_in_use")
        field = self.program.fields.get(pk=target["id"])
        field.field_type = "number"
        with self.assertRaises(ValidationError):
            field.save()
        self.assertEqual(self.program.fields.get(pk=field.pk).field_type, "textarea")

    def test_used_choice_options_preserved_exactly_while_unused_options_can_change(self):
        case = self.payload()["fields"][0]
        self.answer(case["id"], "Задача 1")
        self.assert_error(
            self.put(self.payload(fields=[{**case, "options": ["Новое имя"]}])),
            "field_in_use",
        )
        response = self.put(
            self.payload(fields=[{**case, "options": ["Задача 1", "Новый трек"]}])
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(ProgramSolutionAnswer.objects.get().value, "Задача 1")

    def test_narrowing_constraints_cannot_invalidate_existing_answers(self):
        result = self.put(self.payload(fields=[*self.payload()["fields"], new_field()]))
        target = result.data["form"]["fields"][1]
        self.answer(target["id"], "Длинный ответ")
        invalid = {**target, "validation": {**VALIDATION_DEFAULTS, "max_length": 2}}
        self.assert_error(
            self.put(self.payload(fields=[self.payload()["fields"][0], invalid])),
            "field_in_use",
        )
        valid = {**target, "validation": {**VALIDATION_DEFAULTS, "max_length": 100}}
        self.assertEqual(
            self.put(
                self.payload(fields=[self.payload()["fields"][0], valid])
            ).status_code,
            200,
        )

    def test_template_change_is_blocked_after_answers_in_api_and_admin(self):
        case = self.payload()["fields"][0]
        self.answer(case["id"], "Задача 1")
        self.assert_error(
            self.put(self.payload(template="case_championship")), "template_locked"
        )
        self.program.solution_template = "case_championship"
        with self.assertRaises(ValidationError):
            self.program.full_clean()
        with self.assertRaises(ValidationError):
            self.program.save(update_fields=["solution_template"])

    def test_required_changes_count_only_affected_drafts_and_keep_zero_and_false(self):
        case = self.payload()["fields"][0]
        rows = [
            case,
            new_field("number", position=1, required=True),
            new_field("checkbox", position=2, required=True),
        ]
        result = self.put(self.payload(fields=rows))
        fields = result.data["form"]["fields"]
        self.answer(case["id"], "Задача 1")
        self.answer(fields[1]["id"], 0)
        self.answer(fields[2]["id"], False)
        self.assertEqual(
            call(self.manager, "get", self.root).data["affected_draft_count"], 0
        )
        rows = [*fields, new_field(position=10, required=True)]
        changed = self.put(self.payload(fields=rows))
        self.assertEqual(changed.data["affected_draft_count"], 1)
        self.assertEqual(ProgramSolutionAnswer.objects.count(), 3)

    def test_submitted_snapshot_remains_stable_after_label_order_and_required_changes(
        self,
    ):
        case = self.payload()["fields"][0]
        self.answer(case["id"], "Задача 1")
        before = solution_data(self.solution, self.captain)
        snapshot = dict(
            name=before["name"],
            captain_id=before["captain_id"],
            form=before["form"],
            answers=before["answers"],
            members=before["team"]["members"],
        )
        snapshot["form"]["is_snapshot"] = True
        self.solution.status = "submitted"
        self.solution.submitted_at = timezone.now()
        self.solution.submission_snapshot = snapshot
        self.solution.save()
        changed = self.put(
            self.payload(
                fields=[{**case, "label": "Новая задача"}, new_field(required=True)]
            )
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data["affected_draft_count"], 0)
        read = solution_data(self.solution, self.captain)
        self.assertEqual(read["form"], snapshot["form"])
        self.assertEqual(read["answers"], snapshot["answers"])
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.submission_snapshot, snapshot)

    def test_legacy_form_endpoint_cannot_bypass_solution_definition_rules(self):
        from partner_programs.services.management_form import save_form
        from rest_framework.exceptions import ValidationError as APIValidationError

        with self.assertRaises(APIValidationError):
            save_form(self.program.pk, self.manager, {})


class SolutionFormConcurrencyTests(FormFixture, TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_writes_with_same_revision_serialize(self):
        self.seed()
        payload = self.payload()
        barrier = Barrier(2)

        def write(label):
            close_old_connections()
            data = copy.deepcopy(payload)
            data["fields"][0]["label"] = label
            try:
                barrier.wait(timeout=10)
                solution_forms.save_form(
                    program_id=self.program.pk, actor=self.manager, **data
                )
                return "saved"
            except SolutionError as error:
                return error.payload["code"]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["Первый", "Второй"]))
        self.assertCountEqual(results, ["saved", "form_revision_conflict"])
