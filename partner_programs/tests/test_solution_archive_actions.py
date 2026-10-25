import copy
from time import time
from unittest.mock import patch

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from files.models import UserFile
from files.views import FileView
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from partner_programs.services import solution_archive_actions as actions
from partner_programs.services.solution_analytics import SolutionAnalyticsContext
from partner_programs.solution_api import create_solution
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionAnswer,
    SolutionAdministrativeChange,
    SolutionInvitation,
)
from partner_programs.solution_participants import participant_profiles
from partner_programs.solution_submission import submit_solution
from partner_programs.tests.helpers import (
    create_user,
    create_program_member,
    create_partner_program,
)
from partner_programs.tests.test_solution_forms import call
from partner_programs.tests.test_solution_member_actions import (
    MemberFixture,
    FAST_HASHERS,
)
from project_rates.solution_allocation import assignment_snapshot
from project_rates.solution_assignments import enable_workspace
from projects.models import Project


class ArchiveFixture(MemberFixture):
    def setUp(self):
        super().setUp()
        self.archive_root = f"/programs/{self.program.pk}/management/solutions/archive/"

    def archive_preview(self, ids=None, actor=None):
        return call(
            actor or self.manager,
            "post",
            self.archive_root + "preview/",
            dict(ids=[self.solution.pk] if ids is None else ids),
        )

    def archive_command(self, ids=None):
        ids = [self.solution.pk] if ids is None else ids
        response = self.archive_preview(ids)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["can_apply"], response.data)
        return dict(ids=ids, preview_token=response.data["preview_token"])

    def archive_apply(self, command, actor=None):
        response = call(
            actor or self.manager, "post", self.archive_root + "apply/", command
        )
        self.solution.refresh_from_db()
        return response

    def wire(self, response, status=200, schema="SolutionArchivePreview"):
        return super().wire(response, status, schema)

    def retained(self):
        self.solution.refresh_from_db()
        return dict(
            solution=ProgramSolution.all_objects.filter(pk=self.solution.pk)
            .values()
            .get(),
            members=list(self.solution.members.order_by("pk").values()),
            answers=list(self.solution.answers.order_by("pk").values()),
            invitations=list(self.solution.invitations.order_by("pk").values()),
            assignments=list(self.solution.expert_assignments.order_by("pk").values()),
            scores=list(self.solution.scores.order_by("pk").values()),
            registrations=list(
                PartnerProgramUserProfile.objects.filter(partner_program=self.program)
                .order_by("pk")
                .values()
            ),
            projects=list(Project.objects.order_by("pk").values()),
        )

    def second(self):
        user = create_user()
        create_program_member(self.program, user=user)
        return create_solution(self.program.pk, user, {"name": "Второй черновик"})[0]


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionArchiveActionTests(ArchiveFixture, TestCase):
    def test_preview_is_read_only_and_counts_scored_assignment_and_pending(self):
        pending = SolutionInvitation.objects.create(
            solution=self.solution, recipient=create_user(), role="Дизайнер"
        )
        self.evaluation()
        before = self.retained()
        result = self.wire(self.archive_preview())
        self.assertEqual(result["score_count"], 1)
        self.assertEqual(result["removed_assignments_count"], 1)
        self.assertEqual(result["revoked_invitation_count"], 1)
        self.assertTrue(result["items"][0]["is_submitted"])
        proof = signing.loads(result["preview_token"], salt=actions.SALT)
        self.assertEqual(
            (proof["actor"], proof["program"], proof["ids"]),
            (self.manager.pk, self.program.pk, [self.solution.pk]),
        )
        self.assertEqual(self.retained(), before)
        self.assertTrue(SolutionInvitation.objects.filter(pk=pending.pk).exists())

    def test_submitted_archive_keeps_work_original_submission_scores_roster_and_registration(
        self,
    ):
        pending = SolutionInvitation.objects.create(
            solution=self.solution, recipient=create_user(), role="Дизайнер"
        )
        self.evaluation()
        before = self.retained()
        original = copy.deepcopy(self.solution.submission_snapshot)
        with self.assertRaises(ValidationError), transaction.atomic():
            self.solution.expert_assignments.all().delete()
        response = self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        after = self.retained()
        self.assertEqual(response["changed_count"], 1)
        self.assertEqual(self.solution.submission_snapshot, original)
        self.assertEqual(self.solution.status, "submitted")
        self.assertEqual(self.solution.submitted_at, before["solution"]["submitted_at"])
        self.assertEqual(self.solution.archive_reason, "detached")
        self.assertEqual(self.solution.archived_by_id, self.manager.pk)
        self.assertEqual(self.solution.version, before["solution"]["version"] + 1)
        for key in ("members", "answers", "scores", "registrations", "projects"):
            self.assertEqual(after[key], before[key])
        self.assertFalse(self.solution.expert_assignments.exists())
        self.assertFalse(SolutionInvitation.objects.filter(pk=pending.pk).exists())
        self.assertTrue(
            SolutionInvitation.objects.filter(
                pk=self.invitation.pk, status="accepted"
            ).exists()
        )
        self.assertFalse(ProgramSolution.objects.filter(pk=self.solution.pk).exists())
        self.assertTrue(ProgramSolution.all_objects.filter(pk=self.solution.pk).exists())
        change = self.solution.administrative_changes.get()
        self.assertEqual(change.before_snapshot, original)
        self.assertEqual(change.after_snapshot, original)
        self.assertEqual(change.archive_snapshot, self.solution.archive_snapshot)
        self.assertEqual(change.removed_assignment_ids, [self.assignment.pk])
        self.assertEqual(change.revoked_invitation_ids, [pending.pk])

    def test_draft_archive_has_its_own_material_snapshot_without_submission(self):
        original = call(self.captain, "get", self.url).data
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        saved = self.retained()
        self.assertEqual(self.solution.status, "draft")
        self.assertIsNone(self.solution.submitted_at)
        self.assertIsNone(self.solution.submission_snapshot)
        self.assertEqual(self.solution.archive_snapshot["answers"], original["answers"])
        self.program.fields.update(label="Новая текущая форма")
        current = call(self.captain, "get", self.url)
        self.assertEqual(current.status_code, 200, current.data)
        self.assertTrue(current.data["form"]["is_snapshot"])
        self.assertEqual(current.data["form"]["fields"], original["form"]["fields"])
        self.assertFalse(any(current.data["permissions"].values()))
        self.assertTrue(current.data["team"]["is_frozen"])
        self.assertEqual(current.data["participation"]["status"], "archived")
        self.assertEqual(current.data["answers"], original["answers"])
        self.assertEqual(self.retained(), saved)

    def test_noncompetitive_archive_remains_a_saved_draft(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(is_competitive=False)
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        response = call(self.captain, "get", self.url)
        self.assertFalse(response.data["submission"]["required"])
        self.assertEqual(response.data["submission"]["status"], "draft")
        self.assertIsNone(response.data["submission"]["submitted_at"])
        self.assertIsNone(response.data["readiness"])

    def test_archive_is_owned_read_only_and_excluded_from_default_lists_and_expert_access(
        self,
    ):
        self.evaluation()
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        for actor in [self.captain, self.member, self.manager]:
            detail = call(actor, "get", self.url)
            self.assertEqual(detail.status_code, 200, detail.data)
            self.assertFalse(any(detail.data["permissions"].values()))
            self.assertEqual(
                call(actor, "get", f"/programs/{self.program.pk}/solutions/").data[
                    "count"
                ],
                0,
            )
            self.assertEqual(
                call(
                    actor,
                    "get",
                    f"/programs/{self.program.pk}/solutions/?participation=archived",
                ).data["count"],
                1,
            )
            self.assertEqual(
                call(
                    actor,
                    "get",
                    f"/programs/{self.program.pk}/solutions/?participation=all",
                ).data["count"],
                1,
            )
        for actor in [self.expert, create_user()]:
            self.assertEqual(call(actor, "get", self.url).status_code, 404)
        self.assertEqual(
            call(self.expert, "get", self.url + "evaluation/").status_code, 404
        )
        self.assertEqual(call(self.member, "get", self.history).status_code, 403)
        detail = self.wire(
            call(
                self.manager,
                "get",
                self.history + str(self.solution.administrative_changes.get().pk) + "/",
            ),
            schema="SolutionAdminChangeDetail",
        )
        self.assertEqual(detail["change"]["action"], "archive")
        self.assertEqual(detail["archive_snapshot"], self.solution.archive_snapshot)

    def test_archived_team_does_not_reserve_active_membership_or_captain_uniqueness(self):
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        ctx = call(self.captain, "get", f"/programs/{self.program.pk}/solution-context/")
        self.assertIsNone(ctx.data["current_application"])
        self.assertTrue(ctx.data["can_create"])
        for row in participant_profiles(self.program.pk):
            self.assertFalse(row.is_project_leader or row.is_project_collaborator)
        created = call(
            self.captain,
            "post",
            f"/programs/{self.program.pk}/solutions/",
            dict(name="Новая заявка"),
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertNotEqual(created.data["id"], self.solution.pk)
        root = f'/programs/{self.program.pk}/solutions/{created.data["id"]}/'
        invited = call(
            self.captain,
            "post",
            root + "invitations/",
            dict(
                expected_solution_version=created.data["version"],
                recipient_user_id=self.member.pk,
                role="Аналитик",
            ),
        )
        self.assertEqual(invited.status_code, 201, invited.data)
        accepted = call(
            self.member,
            "post",
            f'/solution-invitations/{invited.data["invitation"]["id"]}/accept/',
            dict(expected_version=invited.data["invitation"]["version"]),
        )
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertEqual(ProgramSolution.objects.filter(program=self.program).count(), 1)
        self.assertEqual(
            ProgramSolution.all_objects.filter(program=self.program).count(), 2
        )
        self.assertTrue(
            ProgramSolution.all_objects.get(pk=self.solution.pk).archive_snapshot
        )

    def test_creation_flag_deadline_and_form_still_control_new_application(self):
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_creation_enabled=False,
            datetime_project_submission_ends=timezone.now() - timezone.timedelta(days=1),
        )
        response = call(
            self.captain, "post", f"/programs/{self.program.pk}/solutions/", {}
        )
        self.assertEqual(response.data["code"], "solution_creation_disabled")
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_creation_enabled=True
        )
        response = call(
            self.captain, "post", f"/programs/{self.program.pk}/solutions/", {}
        )
        self.assertEqual(response.data["code"], "submission_closed")
        self.assertEqual(call(self.captain, "get", self.url).status_code, 200)

    def test_archive_is_allowed_after_deadline_without_current_form_or_creation_flag(
        self,
    ):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_creation_enabled=False,
            solution_template=None,
            datetime_project_submission_ends=timezone.now() - timezone.timedelta(days=1),
        )
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        self.assertEqual(call(self.captain, "get", self.url).status_code, 200)

    def test_archived_materials_are_frozen_through_api_model_and_deletion(self):
        self.evaluation()
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        before = self.retained()
        command = self.command(name="Попытка изменить архив")
        response = call(self.captain, "patch", self.url, command)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "solution_archived")
        for obj in [self.solution, self.membership, self.solution.answers.first()]:
            with self.assertRaises(ValidationError), transaction.atomic():
                obj.save()
            with self.assertRaises(ProtectedError), transaction.atomic():
                obj.delete()
        with self.assertRaises(ProtectedError), transaction.atomic():
            ProgramSolution.all_objects.filter(pk=self.solution.pk).delete()
        self.score.value = "9"
        with self.assertRaises(ValidationError), transaction.atomic():
            self.score.save()
        self.assertEqual(self.retained(), before)

    def test_archived_draft_file_is_protected_before_cdn_and_through_orm(self):
        upload = UserFile.objects.create(
            link="https://example.com/archive.pdf",
            user=self.captain,
            name="Материалы",
            extension="pdf",
            mime_type="application/pdf",
            detected_mime_type="application/pdf",
            size=10,
        )
        ProgramSolutionAnswer.objects.create(
            solution=self.solution,
            field_id=self.fields["file"]["id"],
            value={"url": upload.link},
        )
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        client = APIClient()
        client.force_authenticate(self.captain)
        with patch.object(FileView.cdn, "delete") as cdn:
            response = client.delete("/files/", QUERY_STRING="link=" + upload.link)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "file_in_use")
        cdn.assert_not_called()
        with self.assertRaises(ProtectedError), transaction.atomic():
            UserFile.objects.filter(pk=upload.pk).delete()
        self.assertTrue(UserFile.objects.filter(pk=upload.pk).exists())

    def test_journal_failure_rolls_back_archive_pending_assignments_and_version(self):
        SolutionInvitation.objects.create(
            solution=self.solution, recipient=create_user(), role="Дизайнер"
        )
        self.evaluation()
        command = self.archive_command()
        before = self.retained()
        with patch.object(
            SolutionAdministrativeChange.objects,
            "create",
            side_effect=RuntimeError("journal unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                actions.apply(self.program.pk, self.manager, command)
        self.assertEqual(self.retained(), before)
        self.assertTrue(ProgramSolution.objects.filter(pk=self.solution.pk).exists())
        self.assertEqual(self.solution.administrative_changes.count(), 0)

    def test_bulk_archive_is_atomic_when_one_solution_changed_or_already_archived(self):
        other = self.second()
        command = self.archive_command([other.pk, self.solution.pk])
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        before = self.retained()
        self.wire(self.archive_apply(command), 409)
        self.assertEqual(self.retained(), before)
        self.assertTrue(ProgramSolution.objects.filter(pk=other.pk).exists())
        preview = self.wire(self.archive_preview([other.pk, self.solution.pk]))
        self.assertFalse(preview["can_apply"])
        self.assertIsNone(preview["preview_token"])

    def test_bulk_mixed_draft_and_submitted_are_archived_once_each(self):
        self.evaluation()
        other = self.second()
        result = self.wire(
            self.archive_apply(self.archive_command([other.pk, self.solution.pk])),
            schema="SolutionArchiveReceipt",
        )
        self.assertEqual(result["changed_count"], 2)
        self.assertEqual(
            {r["application"]["solution_id"] for r in result["items"]},
            {other.pk, self.solution.pk},
        )
        self.assertFalse(ProgramSolution.objects.filter(program=self.program).exists())
        self.assertEqual(
            SolutionAdministrativeChange.objects.filter(
                action="archive", solution__program=self.program
            ).count(),
            2,
        )

    def test_replay_expiry_actor_and_selection_binding_do_not_repeat_changes(self):
        other = self.second()
        command = self.archive_command()
        before = self.retained()
        for token in [
            "bad",
            signing.dumps([], salt=actions.SALT),
            signing.dumps({}, salt="solution-case-actions-v1"),
        ]:
            self.wire(self.archive_apply({**command, "preview_token": token}), 409)
        with patch("django.core.signing.time.time", return_value=time() - 601):
            expired = self.archive_command()
        self.wire(self.archive_apply(expired), 409)
        self.wire(self.archive_apply(command, actor=create_user(is_staff=True)), 409)
        self.wire(self.archive_apply({**command, "ids": [other.pk]}), 409)
        self.assertEqual(self.retained(), before)
        self.wire(self.archive_apply(command), schema="SolutionArchiveReceipt")
        after = self.retained()
        self.wire(self.archive_apply(command), 409)
        self.assertEqual(self.retained(), after)
        self.assertEqual(self.solution.administrative_changes.count(), 1)

    def test_permissions_legacy_scope_and_strict_selection_are_preserved(self):
        for actor, status in [
            (None, 401),
            (self.captain, 403),
            (self.member, 403),
            (create_user(), 403),
        ]:
            self.wire(
                call(
                    actor,
                    "post",
                    self.archive_root + "preview/",
                    dict(ids=[self.solution.pk]),
                ),
                status,
            )
        for body in [
            {},
            {"ids": []},
            {"ids": [True]},
            {"ids": ["1"]},
            {"ids": [0]},
            {"ids": [1.5]},
            {"ids": [2**53]},
            {"ids": [self.solution.pk] * 2},
            {"ids": [self.solution.pk], "project_id": 1},
        ]:
            self.wire(
                call(self.manager, "post", self.archive_root + "preview/", body), 400
            )
        self.wire(
            call(
                self.manager,
                "post",
                self.archive_root + "preview/?all=true",
                dict(ids=[self.solution.pk]),
            ),
            400,
        )
        self.wire(self.archive_preview([2**53 - 1]), 404)
        other = create_partner_program(solution_storage_mode="solution")
        self.wire(
            call(
                create_user(is_staff=True),
                "post",
                f"/programs/{other.pk}/management/solutions/archive/preview/",
                dict(ids=[self.solution.pk]),
            ),
            404,
        )
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_storage_mode="legacy_project"
        )
        self.assertEqual(
            self.wire(self.archive_preview(), 409)["code"], "solution_mode_unavailable"
        )

    def test_active_analytics_results_allocation_and_publication_exclude_archived_work(
        self,
    ):
        self.evaluation()
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        self.solution.refresh_from_db()
        self.program.refresh_from_db()
        self.assertFalse(SolutionAnalyticsContext(self.program).solutions)
        self.assertEqual(assignment_snapshot(self.program), [])
        self.program.required_evaluators = None
        self.program.save()
        enable_workspace(self.program)
        self.assertFalse(self.solution.expert_assignments.exists())
        self.assertTrue(self.solution.scores.exists())

    def test_archived_noncompetitive_publication_is_hidden_and_marker_retained(self):
        from partner_programs.services.publishing import publish_solution_program

        now = timezone.now()
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            is_competitive=False,
            publish_projects_after_finish=True,
            datetime_finished=now - timezone.timedelta(days=1),
        )
        self.assertEqual(publish_solution_program(self.program.pk, now=now), 1)
        public = f"/programs/{self.program.pk}/published-solutions/"
        self.assertEqual(call(None, "get", public).data["count"], 1)
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.published_at, now)
        self.assertEqual(call(None, "get", public).data["count"], 0)
        self.assertEqual(
            call(None, "get", public + str(self.solution.pk) + "/").status_code, 404
        )
        self.assertEqual(
            publish_solution_program(
                self.program.pk, now=now + timezone.timedelta(days=1)
            ),
            0,
        )


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionArchiveConcurrencyTests(ArchiveFixture, TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL locks")
        super().setUp()

    def race(self, commands):
        from partner_programs.tests.test_solution_case_actions import (
            SolutionCaseActionConcurrencyTests,
        )

        return SolutionCaseActionConcurrencyTests.race(self, commands)

    def test_two_archival_confirmations_have_one_revision(self):
        self.evaluation()
        command = self.archive_command()
        before = self.retained()

        def archive():
            return actions.apply(self.program.pk, self.manager, command)

        self.assertCountEqual(
            self.race([archive, archive]), ["saved", "solution_action_conflict"]
        )
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, before["solution"]["version"] + 1)
        self.assertEqual(self.solution.administrative_changes.count(), 1)
        self.assertEqual(
            list(self.solution.scores.order_by("pk").values()), before["scores"]
        )

    def test_archive_and_first_submission_leave_a_coherent_saved_work(self):
        command = self.archive_command()
        submit = self.command()
        version = self.solution.version

        def archive():
            return actions.apply(self.program.pk, self.manager, command)

        def send():
            return submit_solution(
                program_id=self.program.pk,
                solution_id=self.solution.pk,
                actor=self.captain,
                **submit,
            )

        result = self.race([archive, send])
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, version + 1)
        if result[0] == "saved":
            self.assertEqual(result, ["saved", "solution_archived"])
            self.assertEqual(self.solution.status, "draft")
            self.assertIsNone(self.solution.submission_snapshot)
            self.assertEqual(len(self.solution.archive_snapshot["members"]), 2)
        else:
            self.assertEqual(result, ["solution_action_conflict", "saved"])
            self.assertIsNone(self.solution.archived_at)
            self.assertEqual(self.solution.status, "submitted")

    def test_archive_and_score_update_preserve_the_committed_score(self):
        self.evaluation()
        command = self.archive_command()
        original = self.score.value

        def archive():
            return actions.apply(self.program.pk, self.manager, command)

        def score():
            self.score.value = "7"
            try:
                self.score.save()
            except ValidationError:
                from partner_programs.solution_errors import SolutionError

                raise SolutionError("solution_archived", "Решение снято с участия.")

        result = self.race([archive, score])
        self.score.refresh_from_db()
        self.solution.refresh_from_db()
        if result[0] == "saved":
            self.assertEqual(result, ["saved", "solution_archived"])
            self.assertEqual(self.score.value, original)
            self.assertIsNotNone(self.solution.archived_at)
        else:
            self.assertEqual(result, ["solution_action_conflict", "saved"])
            self.assertEqual(self.score.value, "7")
            self.assertIsNone(self.solution.archived_at)
