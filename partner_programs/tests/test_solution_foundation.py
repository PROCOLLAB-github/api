import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from django.db import IntegrityError, close_old_connections, transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject
from partner_programs.solution_api import create_solution, form_data, iso
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionAnswer,
    ProgramSolutionMember,
    SolutionInvitation,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
    project_apply_payload,
)
from projects.models import Project


def solution_program(**kwargs):
    program = create_partner_program(
        solution_storage_mode="solution", solution_template="hackathon", **kwargs
    )
    create_program_field(
        program,
        name="case",
        label="Задача",
        field_type="select",
        is_required=True,
        show_filter=True,
        options=["Задача 1"],
    )
    return program


class SolutionFoundationTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.program = solution_program(is_competitive=True)
        create_program_member(self.program, user=self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f"/programs/{self.program.pk}/solutions/"

    def create(self, **data):
        return self.client.post(self.url, data, format="json")

    def context(self):
        return self.client.get(f"/programs/{self.program.pk}/solution-context/")

    def test_create_and_read_match_frozen_contract_without_project(self):
        response = self.create(name="Решение команды")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(Project.objects.exists())
        self.assertFalse(PartnerProgramProject.objects.exists())
        obj = ProgramSolution.objects.get()
        self.assertEqual(obj.members.get().user_id, self.user.pk)
        self.assertEqual(obj.captain_id, self.user.pk)
        self.assertEqual(response.data["team"]["accepted_count"], 1)
        self.assertTrue(response.data["permissions"]["can_manage_team"])
        self.assertTrue(response.data["permissions"]["can_edit"])
        self.assertTrue(response.data["permissions"]["can_invite"])
        self.assertTrue(response.data["permissions"]["can_submit"])
        self.assertEqual(response.data["answers"], [])
        self.assertEqual(response.data["submission"]["status"], "draft")
        self.assertEqual(self.client.get(f"{self.url}{obj.pk}/").data, response.data)
        self.assertEqual(
            self.context().data["current_application"]["solution_id"], obj.pk
        )

        # Validate actual wire responses, not just examples generated from the implementation.
        from jsonschema import Draft202012Validator, FormatChecker

        spec = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text(encoding="utf-8")
        )
        for schema, value in [
            ("Solution", response.data),
            ("Context", self.context().data),
            ("SolutionPage", self.client.get(self.url).data),
        ]:
            Draft202012Validator(
                {
                    "components": spec["components"],
                    "$ref": f"#/components/schemas/{schema}",
                },
                format_checker=FormatChecker(),
            ).validate(value)

    def test_repeat_returns_same_solution_and_does_not_rename_even_after_deadline(self):
        first = self.create(name="Первое")
        self.program.datetime_project_submission_ends = (
            timezone.now() - timezone.timedelta(seconds=1)
        )
        self.program.save()
        repeat = self.create(name="Второе")
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.data["id"], first.data["id"])
        self.assertEqual(repeat.data["name"], "Первое")
        self.assertEqual(ProgramSolution.objects.count(), 1)
        self.assertEqual(ProgramSolutionMember.objects.count(), 1)

    def test_default_program_stays_legacy_and_old_api_still_works(self):
        program = create_partner_program()
        create_program_member(program, user=self.user)
        self.assertEqual(program.solution_storage_mode, "legacy_project")
        result = self.client.post(f"/programs/{program.pk}/solutions/", {}, format="json")
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.data["code"], "solution_mode_unavailable")
        old = self.client.post(
            f"/programs/{program.pk}/projects/apply/",
            project_apply_payload(),
            format="json",
        )
        self.assertEqual(old.status_code, 201, old.data)
        context = self.client.get(f"/programs/{program.pk}/solution-context/").data
        self.assertEqual(context["current_application"]["kind"], "legacy_project")
        self.assertEqual(
            context["current_application"]["program_link_id"], old.data["program_link_id"]
        )

    def test_new_mode_cannot_create_project_through_old_endpoint(self):
        result = self.client.post(
            f"/programs/{self.program.pk}/projects/apply/",
            project_apply_payload(),
            format="json",
        )
        self.assertEqual(result.status_code, 403, result.data)
        self.assertFalse(Project.objects.exists())
        with self.assertRaises(DjangoValidationError):
            PartnerProgramProject.objects.create(
                partner_program=self.program, project=create_project(leader=self.user)
            )

    def test_registration_deadline_configuration_and_manager_exceptions(self):
        outsider = create_user()
        self.client.force_authenticate(outsider)
        self.assertEqual(self.context().data["blocked_reason"], "not_program_member")
        self.assertEqual(self.create().status_code, 403)
        self.program.managers.add(outsider)
        self.assertEqual(self.create().status_code, 201)
        self.client.force_authenticate(self.user)
        self.program.datetime_project_submission_ends = (
            timezone.now() - timezone.timedelta(seconds=1)
        )
        self.program.save()
        self.assertEqual(self.context().data["blocked_reason"], "submission_closed")
        self.assertEqual(self.create().data["code"], "submission_closed")
        self.program.datetime_project_submission_ends = None
        self.program.solution_template = None
        self.program.save()
        self.assertEqual(self.context().data["blocked_reason"], "form_not_configured")
        self.assertEqual(self.create().data["code"], "form_not_configured")
        self.assertEqual(ProgramSolution.objects.count(), 1)

    def test_strict_request_and_identifier_validation(self):
        for data in [
            {"project_id": 1},
            {"name": 1},
            {"name": None},
            {"name": ""},
            {"name": "x" * 257},
            [],
        ]:
            with self.subTest(data=data):
                result = self.client.post(self.url, data, format="json")
                self.assertEqual(result.status_code, 400, result.data)
                self.assertEqual(result.data["code"], "validation_error")
        for path in [
            "/programs/0/solutions/",
            "/programs/9007199254740992/solutions/",
            f"{self.url}9007199254740992/",
        ]:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertFalse(ProgramSolution.objects.exists())

    def test_program_scoping_own_members_manager_and_outsider(self):
        first = self.create().data["id"]
        other_program = solution_program()
        create_program_member(other_program, user=self.user)
        other, _ = create_solution(
            other_program.pk, self.user, {"name": "Другая программа"}
        )
        self.assertNotEqual(first, other.pk)
        self.assertEqual(
            self.client.get(
                f"/programs/{other_program.pk}/solutions/{first}/"
            ).status_code,
            404,
        )
        other_user = create_user()
        self.client.force_authenticate(other_user)
        self.assertEqual(self.client.get(self.url).data["count"], 0)
        self.assertEqual(self.client.get(f"{self.url}{first}/").status_code, 404)
        SolutionInvitation.objects.create(solution_id=first, recipient=other_user)
        self.assertEqual(self.client.get(f"{self.url}{first}/").status_code, 404)
        ProgramSolutionMember.objects.create(solution_id=first, user=other_user)
        self.assertEqual(self.client.get(f"{self.url}{first}/").status_code, 200)
        self.assertEqual(self.create().data["code"], "already_in_program_team")
        self.assertEqual(self.context().data["current_application"]["solution_id"], first)
        ProgramSolutionMember.objects.filter(user=other_user).delete()
        other_program.managers.add(other_user)
        self.assertEqual(self.client.get(f"{self.url}{first}/").status_code, 404)
        self.program.managers.add(other_user)
        self.assertEqual(self.client.get(f"{self.url}{first}/").status_code, 200)

    def test_legacy_reference_and_ambiguous_links_are_not_chosen_arbitrarily(self):
        link = create_program_project(
            self.program, project=create_project(leader=self.user)
        )
        self.assertEqual(
            self.context().data["current_application"]["program_link_id"], link.pk
        )
        self.assertEqual(self.create().data["code"], "already_in_program_team")
        create_program_project(self.program, project=create_project(leader=self.user))
        self.assertEqual(self.context().status_code, 409)
        self.assertEqual(self.context().data["code"], "ambiguous_application")
        self.assertFalse(ProgramSolution.objects.exists())

    def test_collection_filter_pagination_and_noncompetitive_submission(self):
        self.create(name="Alpha")
        manager = create_user()
        self.program.managers.add(manager)
        create_solution(self.program.pk, manager, {"name": "Beta"})
        self.client.force_authenticate(manager)
        page = self.client.get(self.url, {"limit": 1}).data
        self.assertEqual(page["count"], 2)
        self.assertIn("offset=1", page["next"])
        self.assertEqual(self.client.get(self.url, {"search": "Beta"}).data["count"], 1)
        self.assertEqual(
            self.client.get(self.url, {"submission": "submitted"}).data["count"], 0
        )
        for query in [
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
            {"unknown": 1},
            {"submission": "bad"},
        ]:
            self.assertEqual(self.client.get(self.url, query).status_code, 400)
        self.program.is_competitive = False
        self.program.save()
        self.assertEqual(
            self.client.get(self.url, {"submission": "submitted"}).status_code, 400
        )
        self.assertIsNone(
            self.client.get(f"{self.url}{ProgramSolution.objects.first().pk}/").data[
                "readiness"
            ]
        )

    def test_schema_revision_tracks_configuration_and_read_survives_mode_rollback(self):
        solution = self.create().data
        revision = solution["form"]["revision"]
        field = self.program.fields.get()
        field.label = "Новая подпись"
        field.save()
        self.assertNotEqual(form_data(self.program)["revision"], revision)
        self.program.solution_storage_mode = "legacy_project"
        self.program.save()
        self.assertEqual(self.client.get(f"{self.url}{solution['id']}/").status_code, 200)
        self.assertEqual(self.create().status_code, 409)

    def test_read_and_collection_keep_stored_submitted_representation(self):
        data = self.create(name="Сданное решение").data
        field = self.program.fields.get()
        stamp = timezone.now()
        snapshot = dict(
            name=data["name"],
            captain_id=self.user.pk,
            members=data["team"]["members"],
            form={**data["form"], "is_snapshot": True},
            answers=[dict(field_id=field.pk, value="Задача 1")],
            submitted_at=iso(stamp),
        )
        ProgramSolution.objects.filter(pk=data["id"]).update(
            status="submitted",
            submitted_at=stamp,
            submission_snapshot=snapshot,
            name="Другое название",
        )
        field.label = "Новая подпись"
        field.save()
        response = self.client.get(f"{self.url}{data['id']}/").data
        self.assertEqual(response["name"], "Сданное решение")
        self.assertEqual(response["form"], snapshot["form"])
        self.assertEqual(response["answers"], snapshot["answers"])
        self.assertTrue(response["team"]["is_frozen"])
        summary = self.client.get(self.url).data["results"][0]
        self.assertEqual(summary["name"], "Сданное решение")
        self.assertEqual(summary["case_value"], "Задача 1")

    def test_rights_precede_deadline_and_staff_does_not_gain_registration_exception(self):
        outsider = create_user(is_staff=True)
        self.client.force_authenticate(outsider)
        self.program.datetime_project_submission_ends = (
            timezone.now() - timezone.timedelta(seconds=1)
        )
        self.program.save()
        self.assertEqual(self.context().data["blocked_reason"], "not_program_member")
        result = self.create()
        self.assertEqual(result.status_code, 403)
        self.assertEqual(result.data["code"], "not_program_member")

    def test_foundation_constraints_and_no_team_mutation_endpoints(self):
        solution_id = self.create().data["id"]
        solution = ProgramSolution.objects.get(pk=solution_id)
        invalid = [
            lambda: ProgramSolution.objects.create(
                program=self.program, captain=self.user
            ),
            lambda: ProgramSolutionMember.objects.create(
                solution=solution, user=self.user
            ),
            lambda: ProgramSolution.objects.filter(pk=solution.pk).update(version=0),
            lambda: ProgramSolution.objects.filter(pk=solution.pk).update(
                status="submitted"
            ),
        ]
        invitation = SolutionInvitation.objects.create(
            solution=solution, recipient=create_user()
        )
        invalid.append(
            lambda: SolutionInvitation.objects.create(
                solution=solution, recipient=invitation.recipient
            )
        )
        field = self.program.fields.get()
        ProgramSolutionAnswer.objects.create(solution=solution, field=field, value=False)
        invalid.append(
            lambda: ProgramSolutionAnswer.objects.create(
                solution=solution, field=field, value=0
            )
        )
        for action in invalid:
            with self.subTest(action=action), self.assertRaises(
                IntegrityError
            ), transaction.atomic():
                action()
        self.assertEqual(
            self.client.patch(
                f"{self.url}{solution_id}/", {"name": "X"}, format="json"
            ).status_code,
            400,
        )
        for suffix, expected_status in [("members/", 404), ("submit/", 400)]:
            self.assertEqual(
                self.client.post(
                    f"{self.url}{solution_id}/{suffix}", {}, format="json"
                ).status_code,
                expected_status,
            )

    def test_anonymous_api_uses_contract_error_envelope(self):
        self.client.force_authenticate(None)
        for url in [self.url, f"/programs/{self.program.pk}/solution-context/"]:
            result = self.client.get(url)
            self.assertEqual(result.status_code, 401)
            self.assertEqual(set(result.data), {"code", "detail", "errors", "meta"})


@skipUnlessDBFeature("has_select_for_update")
class SolutionCreationConcurrencyTests(TransactionTestCase):
    def test_concurrent_create_serializes_on_program_and_returns_one_solution(self):
        program = solution_program()
        user = create_user()
        create_program_member(program, user=user)
        barrier = Barrier(2)

        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                obj, created = create_solution(program.pk, user, {"name": "Одновременно"})
                return obj.pk, created
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(len({pk for pk, _ in results}), 1)
        self.assertEqual(sorted(created for _, created in results), [False, True])
        self.assertEqual(ProgramSolution.objects.count(), 1)
        self.assertEqual(ProgramSolutionMember.objects.count(), 1)
        self.assertFalse(Project.objects.exists())
