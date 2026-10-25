from time import time
from unittest.mock import patch

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from partner_programs.services import solution_archive_actions as archive
from partner_programs.services import solution_registration_actions as actions
from partner_programs.solution_models import (
    ProgramSolutionMember,
    SolutionAdministrativeChange,
    SolutionInvitation,
    SolutionRegistrationRemoval,
)
from partner_programs.tests.helpers import (
    create_user,
    create_program_member,
    create_partner_program,
    create_program_project,
)
from partner_programs.tests.test_solution_archive_actions import ArchiveFixture
from partner_programs.tests.test_solution_forms import call
from partner_programs.tests.test_solution_member_actions import FAST_HASHERS
from projects.models import Project
from users.models import CustomUser


class RegistrationFixture(ArchiveFixture):
    def setUp(self):
        super().setUp()
        self.removal_root = (
            f"/programs/{self.program.pk}/management/registrations/remove/"
        )
        self.audit_root = (
            f"/programs/{self.program.pk}/management/registrations/removals/"
        )

    def registration_ids(self, *users):
        return list(
            PartnerProgramUserProfile.objects.filter(
                partner_program=self.program, user__in=users or [self.member]
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )

    def removal_preview(self, ids=None, actor=None):
        return call(
            actor or self.manager,
            "post",
            self.removal_root + "preview/",
            dict(registration_ids=self.registration_ids() if ids is None else ids),
        )

    def removal_command(self, ids=None):
        ids = self.registration_ids() if ids is None else ids
        response = self.wire(self.removal_preview(ids))
        self.assertTrue(response["can_apply"], response)
        return dict(registration_ids=ids, preview_token=response["preview_token"])

    def remove(self, command=None, actor=None):
        return call(
            actor or self.manager,
            "post",
            self.removal_root + "apply/",
            self.removal_command() if command is None else command,
        )

    def wire(self, response, status=200, schema="SolutionRegistrationRemovalPreview"):
        return super().wire(response, status, schema)

    def audit(self, audit_id):
        return self.wire(
            call(self.manager, "get", self.audit_root + str(audit_id) + "/"),
            schema="SolutionRegistrationRemovalAuditDetail",
        )


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionRegistrationActionTests(RegistrationFixture, TestCase):
    def test_preview_read_only_binds_profile_ids_and_minimal_snapshot(self):
        self.evaluation()
        before = self.retained()
        result = self.wire(self.removal_preview())
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["removed_member_count"], 1)
        self.assertEqual(result["effects"][0]["effect"], "remove_members")
        self.assertEqual(result["score_count"], 1)
        self.assertEqual(result["removed_assignments_count"], 0)
        proof = signing.loads(result["preview_token"], salt=actions.SALT)
        self.assertEqual(proof["registration_ids"], [self.registration.pk])
        self.assertEqual(proof["actor"], self.manager.pk)
        self.assertEqual(proof["program"], self.program.pk)
        self.assertEqual(set(result["registrations"][0]), {"registration_id", "user"})
        self.assertEqual(self.retained(), before)
        self.assertFalse(SolutionRegistrationRemoval.objects.exists())

    def test_submitted_member_removal_retains_answers_scores_assignments_processed_invite_and_user(
        self,
    ):
        self.evaluation()
        before = self.retained()
        response = self.wire(self.remove(), schema="SolutionRegistrationRemovalReceipt")
        self.solution.refresh_from_db()
        after = self.retained()
        for key in ("answers", "scores", "assignments", "invitations", "projects"):
            self.assertEqual(after[key], before[key])
        self.assertFalse(
            PartnerProgramUserProfile.objects.filter(pk=self.registration.pk).exists()
        )
        self.assertTrue(CustomUser.objects.filter(pk=self.member.pk).exists())
        self.assertEqual(self.solution.status, "submitted")
        self.assertEqual(self.solution.submitted_at, before["solution"]["submitted_at"])
        self.assertEqual(self.solution.version, before["solution"]["version"] + 1)
        self.assertEqual(
            [m["user"]["id"] for m in self.solution.submission_snapshot["members"]],
            [self.captain.pk],
        )
        change = self.solution.administrative_changes.get()
        self.assertEqual(
            change.before_snapshot, before["solution"]["submission_snapshot"]
        )
        self.assertEqual(change.after_snapshot, self.solution.submission_snapshot)
        self.assertEqual(change.removed_members[0]["user"]["id"], self.member.pk)
        self.assertEqual(change.registration_removal_id, response["audit_id"])
        self.assertEqual(call(self.member, "get", self.url).status_code, 404)
        self.assertEqual(call(self.captain, "get", self.url).status_code, 200)
        audit = self.audit(response["audit_id"])
        self.assertEqual(audit["changes"][0]["action"], "remove_registrations")
        self.wire(
            call(self.manager, "get", self.history + str(change.pk) + "/"),
            schema="SolutionAdminChangeDetail",
        )

    def test_captain_and_member_selection_archives_once_preserving_roster_and_submission(
        self,
    ):
        SolutionInvitation.objects.create(
            solution=self.solution, recipient=create_user(), role="Дизайнер"
        )
        self.evaluation()
        before = self.retained()
        ids = self.registration_ids(self.captain, self.member)
        response = self.wire(
            self.remove(self.removal_command(ids)),
            schema="SolutionRegistrationRemovalReceipt",
        )
        self.solution.refresh_from_db()
        after = self.retained()
        self.assertEqual(response["deleted_count"], 2)
        self.assertEqual(len(response["items"]), 1)
        self.assertEqual(self.solution.archive_reason, "registration_removed")
        for key in ("answers", "members", "scores", "projects"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(
            self.solution.submission_snapshot, before["solution"]["submission_snapshot"]
        )
        self.assertFalse(self.solution.expert_assignments.exists())
        self.assertFalse(self.solution.invitations.filter(status="pending").exists())
        self.assertTrue(self.solution.invitations.filter(status="accepted").exists())
        self.assertEqual(call(self.captain, "get", self.url).status_code, 200)
        event = self.audit(response["audit_id"])["changes"][0]
        self.assertEqual(event["reason"], "registration_removed")
        self.assertEqual(event["registration_removal_id"], response["audit_id"])

    def test_draft_captain_archive_without_artificial_submission(self):
        response = self.wire(
            self.remove(self.removal_command(self.registration_ids(self.captain))),
            schema="SolutionRegistrationRemovalReceipt",
        )
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.status, "draft")
        self.assertIsNone(self.solution.submitted_at)
        self.assertIsNone(self.solution.submission_snapshot)
        self.assertIsNotNone(self.solution.archive_snapshot)
        self.assertEqual(
            self.audit(response["audit_id"])["changes"][0]["action"], "archive"
        )

    def test_pending_only_revoked_with_revision_and_audit_but_roster_unchanged(self):
        user = create_user()
        registration = create_program_member(self.program, user=user)
        pending = SolutionInvitation.objects.create(
            solution=self.solution, recipient=user, role="Дизайнер"
        )
        self.evaluation()
        before = self.retained()
        response = self.wire(
            self.remove(self.removal_command([registration.pk])),
            schema="SolutionRegistrationRemovalReceipt",
        )
        after = self.retained()
        self.assertEqual(after["members"], before["members"])
        self.assertEqual(
            after["solution"]["submission_snapshot"],
            before["solution"]["submission_snapshot"],
        )
        self.assertFalse(SolutionInvitation.objects.filter(pk=pending.pk).exists())
        change = self.solution.administrative_changes.get()
        self.assertEqual(change.removed_members, [])
        self.assertEqual(change.revoked_invitation_ids, [pending.pk])
        self.assertEqual(self.audit(response["audit_id"])["audit"]["deleted_count"], 1)

    def test_registration_without_solution_keeps_global_audit(self):
        user = create_user()
        registration = create_program_member(self.program, user=user)
        command = self.removal_command([registration.pk])
        response = self.wire(
            self.remove(command), schema="SolutionRegistrationRemovalReceipt"
        )
        self.assertEqual(response["items"], [])
        audit = self.audit(response["audit_id"])
        self.assertEqual(audit["changes"], [])
        self.assertEqual(
            audit["audit"]["registrations"][0]["registration_id"], registration.pk
        )
        self.wire(
            call(self.manager, "get", self.audit_root),
            schema="SolutionRegistrationRemovalAuditPage",
        )
        self.wire(self.remove(command), 409)
        self.assertEqual(SolutionRegistrationRemoval.objects.count(), 1)

    def test_person_display_changes_invalidate_preview_without_a_solution(self):
        user = create_user()
        registration = create_program_member(self.program, user=user)
        command = self.removal_command([registration.pk])
        CustomUser.objects.filter(pk=user.pk).update(first_name="Новое имя")
        self.wire(self.remove(command), 409)
        self.assertTrue(
            PartnerProgramUserProfile.objects.filter(pk=registration.pk).exists()
        )
        self.assertFalse(SolutionRegistrationRemoval.objects.exists())

    def test_existing_archived_roster_snapshots_and_history_unchanged(self):
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        before = self.retained()
        events = list(SolutionAdministrativeChange.objects.values())
        response = self.wire(self.remove(), schema="SolutionRegistrationRemovalReceipt")
        after = self.retained()
        for key in (
            "solution",
            "members",
            "answers",
            "invitations",
            "assignments",
            "scores",
            "projects",
        ):
            self.assertEqual(after[key], before[key])
        self.assertEqual(list(SolutionAdministrativeChange.objects.values()), events)
        self.assertEqual(response["items"], [])

    def test_other_program_registration_and_legacy_project_rows_unchanged(self):
        other = create_partner_program()
        registration = create_program_member(other, user=self.member)
        link = create_program_project(other)
        before = list(Project.objects.order_by("pk").values())
        original = (
            PartnerProgramUserProfile.objects.filter(pk=registration.pk).values().get()
        )
        self.wire(self.remove(), schema="SolutionRegistrationRemovalReceipt")
        self.assertEqual(list(Project.objects.order_by("pk").values()), before)
        self.assertEqual(
            PartnerProgramUserProfile.objects.filter(pk=registration.pk).values().get(),
            original,
        )
        self.assertTrue(other.program_projects.filter(pk=link.pk).exists())

    def test_mixed_legacy_profile_link_blocks_whole_selection(self):
        link = create_program_project(self.program)
        PartnerProgramUserProfile.objects.filter(pk=self.registration.pk).update(
            project=link.project
        )
        before = self.retained()
        self.assertEqual(
            self.wire(self.removal_preview(), 409)["code"], "legacy_application_conflict"
        )
        self.assertEqual(self.retained(), before)

    def test_legacy_captain_link_without_profile_project_also_blocks(self):
        link = create_program_project(self.program)
        Project.objects.filter(pk=link.project_id).update(leader=self.member)
        self.assertEqual(
            self.wire(self.removal_preview(), 409)["code"], "legacy_application_conflict"
        )
        self.assertTrue(
            PartnerProgramUserProfile.objects.filter(pk=self.registration.pk).exists()
        )

    def test_legacy_program_rejected_without_mutation(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_storage_mode="legacy_project"
        )
        before = self.retained()
        self.assertEqual(
            self.wire(self.removal_preview(), 409)["code"], "solution_mode_unavailable"
        )
        self.assertEqual(self.retained(), before)

    def test_replay_wrong_actor_expiry_tampered_and_stale_are_atomic(self):
        command = self.removal_command()
        before = self.retained()
        self.wire(self.remove({**command, "preview_token": "invalid"}), 409)
        with patch("django.core.signing.time.time", return_value=time() + 601):
            self.wire(self.remove(command), 409)
        other = create_user(is_staff=True)
        self.wire(self.remove(command, other), 409)
        self.assertEqual(self.retained(), before)
        self.wire(self.remove(command), schema="SolutionRegistrationRemovalReceipt")
        saved = self.retained()
        self.wire(self.remove(command), 409)
        self.assertEqual(self.retained(), saved)

    def test_registration_data_or_score_changes_invalidate_confirmation(self):
        self.evaluation()
        command = self.removal_command()
        PartnerProgramUserProfile.objects.filter(pk=self.registration.pk).update(
            partner_program_data={"new": "value"}
        )
        self.wire(self.remove(command), 409)
        command = self.removal_command()
        self.score.value = "7"
        self.score.save()
        self.wire(self.remove(command), 409)
        self.assertTrue(self.solution.members.filter(user=self.member).exists())
        self.assertFalse(SolutionRegistrationRemoval.objects.exists())

    def test_all_effects_and_profile_deletion_roll_back_if_audit_or_delete_fails(self):
        command = self.removal_command()
        before = self.retained()
        with patch.object(
            SolutionAdministrativeChange.objects,
            "create",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                actions.apply(self.program.pk, self.manager, command)
        self.assertEqual(self.retained(), before)
        self.assertFalse(SolutionRegistrationRemoval.objects.exists())

    def test_profile_signal_failure_rolls_back_captain_archive_and_all_audits(self):
        from django.db.models.signals import pre_delete

        command = self.removal_command(self.registration_ids(self.captain))
        before = self.retained()

        def fail(sender, instance, **kwargs):
            raise RuntimeError("registration delete unavailable")

        pre_delete.connect(fail, sender=PartnerProgramUserProfile, weak=False)
        try:
            with self.assertRaises(RuntimeError):
                actions.apply(self.program.pk, self.manager, command)
        finally:
            pre_delete.disconnect(fail, sender=PartnerProgramUserProfile)
        self.assertEqual(self.retained(), before)
        self.assertFalse(SolutionRegistrationRemoval.objects.exists())

    def test_permission_scope_and_revocation_checked_again(self):
        self.wire(self.removal_preview(actor=self.member), 403)
        foreign = create_program_member(create_partner_program(), user=self.member)
        self.wire(self.removal_preview([foreign.pk]), 404)
        command = self.removal_command()
        self.program.managers.remove(self.manager)
        self.wire(self.remove(command), 403)
        self.assertTrue(
            PartnerProgramUserProfile.objects.filter(pk=self.registration.pk).exists()
        )

    def test_strict_requests_unknown_query_and_unsafe_ids(self):
        for data in [
            {"registration_ids": []},
            {"registration_ids": [self.registration.pk] * 2},
            {"registration_ids": [True]},
            {"registration_ids": [2**53]},
            {"user_id": self.member.pk},
            {"registration_ids": [self.registration.pk], "project_id": 1},
        ]:
            self.wire(
                call(self.manager, "post", self.removal_root + "preview/", data), 400
            )
        self.wire(
            call(
                self.manager,
                "post",
                self.removal_root + "preview/?all=true",
                dict(registration_ids=self.registration_ids()),
            ),
            400,
        )
        self.wire(
            call(
                self.manager,
                "post",
                self.removal_root + "apply/",
                dict(registration_ids=self.registration_ids()),
            ),
            400,
        )

    def test_audit_read_scope_pagination_and_immutable_model_queryset_admin(self):
        response = self.wire(self.remove(), schema="SolutionRegistrationRemovalReceipt")
        audit = SolutionRegistrationRemoval.objects.get(pk=response["audit_id"])
        self.wire(call(self.member, "get", self.audit_root), 403)
        other = create_partner_program(solution_storage_mode="solution")
        other.managers.add(self.manager)
        self.wire(
            call(
                self.manager,
                "get",
                self.audit_root.replace(f"/{self.program.pk}/", f"/{other.pk}/")
                + str(audit.pk)
                + "/",
            ),
            404,
        )
        for query in [dict(limit=101), dict(offset=-1), dict(all=True)]:
            self.wire(call(self.manager, "get", self.audit_root, query), 400)
        with self.assertRaises(ValidationError):
            audit.save()
        with self.assertRaises(ValidationError):
            audit.delete()
        with self.assertRaises(ValidationError):
            SolutionRegistrationRemoval.objects.filter(pk=audit.pk).update(
                deleted_count=2
            )
        with self.assertRaises(ValidationError):
            SolutionRegistrationRemoval.objects.filter(pk=audit.pk).delete()
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.program.delete()
        from django.contrib import admin
        from partner_programs.solution_admin import SolutionRegistrationRemovalAdmin

        model_admin = SolutionRegistrationRemovalAdmin(
            SolutionRegistrationRemoval, admin.site
        )
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None, audit))
        self.assertFalse(model_admin.has_delete_permission(None, audit))

    def test_closed_program_creation_switch_and_missing_current_form_do_not_block_exception(
        self,
    ):
        self.evaluation()
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_creation_enabled=False,
            solution_template=None,
            datetime_finished=timezone.now() - timezone.timedelta(days=1),
        )
        self.wire(self.remove(), schema="SolutionRegistrationRemovalReceipt")

    def test_manager_expert_and_auth_roles_survive_registration_deletion(self):
        self.evaluation()
        manager_registration = create_program_member(self.program, user=self.manager)
        expert_registration = create_program_member(self.program, user=self.expert)
        ids = [self.registration.pk, manager_registration.pk, expert_registration.pk]
        before = list(
            CustomUser.objects.filter(
                pk__in=[self.member.pk, self.manager.pk, self.expert.pk]
            )
            .order_by("pk")
            .values()
        )
        scores = list(self.solution.scores.values())
        assignments = list(self.solution.expert_assignments.values())
        response = self.wire(
            self.remove(self.removal_command(ids)),
            schema="SolutionRegistrationRemovalReceipt",
        )
        self.assertEqual(response["deleted_count"], 3)
        self.assertTrue(self.program.is_manager(self.manager))
        self.assertTrue(self.expert.expert.programs.filter(pk=self.program.pk).exists())
        self.assertEqual(list(self.solution.scores.values()), scores)
        self.assertEqual(list(self.solution.expert_assignments.values()), assignments)
        self.assertEqual(
            list(
                CustomUser.objects.filter(
                    pk__in=[self.member.pk, self.manager.pk, self.expert.pk]
                )
                .order_by("pk")
                .values()
            ),
            before,
        )

    def test_two_selected_members_create_one_grouped_revision_and_keep_captain(self):
        user = create_user()
        registration = create_program_member(self.program, user=user)
        ProgramSolutionMember.objects.create(
            solution=self.solution, user=user, role="Дизайнер"
        )
        self.evaluation()
        response = self.wire(
            self.remove(self.removal_command([self.registration.pk, registration.pk])),
            schema="SolutionRegistrationRemovalReceipt",
        )
        self.solution.refresh_from_db()
        self.assertEqual(len(response["items"]), 1)
        self.assertEqual(self.solution.members.count(), 1)
        self.assertEqual(len(self.solution.submission_snapshot["members"]), 1)
        self.assertEqual(self.solution.administrative_changes.count(), 1)
        self.assertEqual(
            len(self.solution.administrative_changes.get().removed_members), 2
        )

    def test_noncompetitive_draft_keeps_answers_and_has_no_submission(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(is_competitive=False)
        before = self.retained()
        self.wire(self.remove(), schema="SolutionRegistrationRemovalReceipt")
        after = self.retained()
        self.assertEqual(after["answers"], before["answers"])
        self.assertEqual(after["solution"]["status"], "draft")
        self.assertIsNone(after["solution"]["submission_snapshot"])
        self.assertIsNone(self.solution.administrative_changes.get().before_snapshot)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionRegistrationConcurrencyTests(RegistrationFixture, TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL locks")
        super().setUp()

    def race(self, commands):
        from partner_programs.tests.test_solution_case_actions import (
            SolutionCaseActionConcurrencyTests,
        )

        return SolutionCaseActionConcurrencyTests.race(self, commands)

    def test_two_confirmations_produce_one_profile_deletion_and_revision(self):
        self.evaluation()
        command = self.removal_command()
        self.solution.refresh_from_db()
        before = self.solution.version

        def remove():
            return actions.apply(self.program.pk, self.manager, command)

        self.assertCountEqual(
            self.race([remove, remove]), ["saved", "solution_action_conflict"]
        )
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.version, before + 1)
        self.assertEqual(SolutionRegistrationRemoval.objects.count(), 1)
        self.assertEqual(self.solution.scores.count(), 1)
        self.assertEqual(self.solution.expert_assignments.count(), 1)

    def test_captain_removal_and_detach_produce_one_archive(self):
        command = self.removal_command(self.registration_ids(self.captain))
        detach = self.archive_command()

        def remove():
            return actions.apply(self.program.pk, self.manager, command)

        def withdraw():
            return archive.apply(self.program.pk, self.manager, detach)

        result = self.race([remove, withdraw])
        self.solution.refresh_from_db()
        if result[0] == "saved":
            self.assertEqual(result, ["saved", "solution_action_conflict"])
            self.assertEqual(SolutionRegistrationRemoval.objects.count(), 1)
        else:
            self.assertEqual(result, ["solution_action_conflict", "saved"])
            self.assertEqual(SolutionRegistrationRemoval.objects.count(), 0)
        self.assertEqual(self.solution.administrative_changes.count(), 1)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SolutionRegistrationMigrationTests(RegistrationFixture, TransactionTestCase):
    def test_additive_migration_preserves_archived_work_and_preceding_history(self):
        self.evaluation()
        self.wire(
            self.archive_apply(self.archive_command()), schema="SolutionArchiveReceipt"
        )
        before = self.retained()
        executor = MigrationExecutor(connection)
        leaf = executor.loader.graph.leaf_nodes()
        old = [("partner_programs", "0037_solution_archive_retention")]
        try:
            executor.migrate(old)
            historical = executor.loader.project_state(old).apps
            history_model = historical.get_model(
                "partner_programs", "SolutionAdministrativeChange"
            )
            columns = [f.attname for f in history_model._meta.fields]
            history = list(history_model.objects.order_by("pk").values(*columns))
            executor = MigrationExecutor(connection)
            executor.migrate(leaf)
            self.assertEqual(self.retained(), before)
            self.assertEqual(
                list(
                    SolutionAdministrativeChange.objects.order_by("pk").values(*columns)
                ),
                history,
            )
            self.assertFalse(SolutionRegistrationRemoval.objects.exists())
        finally:
            MigrationExecutor(connection).migrate(leaf)
