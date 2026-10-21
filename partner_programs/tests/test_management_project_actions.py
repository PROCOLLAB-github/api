from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from unittest.mock import patch
from django.test import TestCase
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.db import close_old_connections, connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from project_rates.models import (
    Criteria,
    ExpertCaseScope,
    ProjectExpertAssignment,
    ProjectScore,
)
from project_rates.tests.helpers import create_rate_expert
from projects.models import Collaborator, Project
from partner_programs.services.management_project_actions import (
    ActionConflict,
    apply_action,
    preview_action,
)


class ManagementProjectActionsTests(TestCase):
    def setUp(self):
        self.program = create_partner_program(is_competitive=True, max_project_rates=3)
        self.manager = create_user()
        self.program.managers.add(self.manager)
        self.case = PartnerProgramField.objects.create(
            partner_program=self.program,
            name="case",
            label="Кейс",
            field_type="select",
            is_required=True,
            show_filter=True,
            options="Банк|Город",
        )
        self.deck = PartnerProgramField.objects.create(
            partner_program=self.program,
            name="deck",
            label="Презентация",
            field_type="file",
            is_required=True,
        )
        self.link = self.make_link()
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.root = f"/programs/{self.program.pk}/management/projects/actions/"

    def make_link(self):
        leader = create_program_member(self.program).user
        link = create_program_project(self.program, project=create_project(leader=leader))
        PartnerProgramFieldValue.objects.create(
            program_project=link, field=self.case, value_text="Банк"
        )
        PartnerProgramFieldValue.objects.create(
            program_project=link,
            field=self.deck,
            value_text="https://example.test/deck.pdf",
        )
        return link

    def preview(self, action="submit", ids=None, **kwargs):
        return self.client.post(
            self.root + "preview/",
            {"action": action, "ids": ids or [self.link.pk], **kwargs},
            format="json",
        )

    def apply(self, preview, action="submit", ids=None, **kwargs):
        return self.client.post(
            self.root + "apply/",
            {
                "action": action,
                "ids": ids or [self.link.pk],
                "preview_token": preview.data["preview_token"],
                **kwargs,
            },
            format="json",
        )

    def test_submit_after_deadline_validates_and_preserves_old_leader_contract(self):
        type(self.program).objects.filter(pk=self.program.pk).update(
            datetime_project_submission_ends=timezone.now() - timedelta(days=1)
        )
        preview = self.preview()
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data["can_apply"])
        self.assertIn("no-store", preview["Cache-Control"])
        self.assertFalse(PartnerProgramProject.objects.get(pk=self.link.pk).submitted)
        response = self.apply(preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.link.refresh_from_db()
        self.assertTrue(self.link.submitted)
        self.assertIsNotNone(self.link.datetime_submitted)
        other = self.make_link()
        from partner_programs.services.project_fields import submit_program_project
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            submit_program_project(other.pk, other.project.leader)

    def test_required_fields_choice_file_and_false_checkbox(self):
        self.link.field_values.filter(field=self.deck).delete()
        preview = self.preview()
        self.assertFalse(preview.data["can_apply"])
        self.assertIn("Презентация", str(preview.data["items"][0]["errors"]))
        PartnerProgramFieldValue.objects.bulk_create(
            [
                PartnerProgramFieldValue(
                    program_project=self.link, field=self.deck, value_text="invalid"
                )
            ]
        )
        self.assertFalse(self.preview().data["can_apply"])
        self.link.field_values.filter(field=self.deck).update(
            value_text="https://example.test/deck.pdf"
        )
        self.link.field_values.filter(field=self.case).update(value_text="Удаленный кейс")
        self.assertFalse(self.preview().data["can_apply"])
        self.link.field_values.filter(field=self.case).update(value_text="Банк")
        check = PartnerProgramField.objects.create(
            partner_program=self.program,
            name="check",
            label="Чекбокс",
            field_type="checkbox",
            is_required=True,
        )
        PartnerProgramFieldValue.objects.create(
            program_project=self.link, field=check, value_text="false"
        )
        self.assertTrue(self.preview().data["can_apply"])

    def test_bulk_is_atomic_and_already_submitted_dates_unchanged(self):
        second = self.make_link()
        second.field_values.filter(field=self.deck).delete()
        preview = self.preview(ids=[self.link.pk, second.pk])
        self.assertFalse(preview.data["can_apply"])
        self.assertIsNone(preview.data["preview_token"])
        self.assertFalse(
            PartnerProgramProject.objects.filter(
                pk__in=[self.link.pk, second.pk], submitted=True
            ).exists()
        )
        PartnerProgramFieldValue.objects.create(
            program_project=second,
            field=self.deck,
            value_text="https://example.test/deck.pdf",
        )
        prior = timezone.now() - timedelta(days=2)
        PartnerProgramProject.objects.filter(pk=second.pk).update(
            submitted=True, datetime_submitted=prior
        )
        preview = self.preview(ids=[second.pk, self.link.pk, second.pk])
        self.assertEqual(preview.data["already_submitted_count"], 1)
        response = self.apply(preview, ids=[second.pk, self.link.pk])
        self.assertEqual(response.data["changed_count"], 1)
        second.refresh_from_db()
        self.assertEqual(second.datetime_submitted, prior)
        self.assertFalse(self.preview().data["can_apply"])

    def test_draft_team_and_noncompetitive_block_submission(self):
        Project.objects.filter(pk=self.link.project_id).update(draft=True)
        self.assertIn("черновике", str(self.preview().data["items"]))
        Project.objects.filter(pk=self.link.project_id).update(draft=False)
        type(self.program).objects.filter(pk=self.program.pk).update(
            legacy_team_min_size=2
        )
        self.assertFalse(self.preview().data["can_apply"])

    def test_legacy_case_configuration_does_not_bypass_case_validation(self):
        PartnerProgramField.objects.filter(pk=self.case.pk).update(
            is_required=False, field_type="text"
        )
        self.link.field_values.filter(field=self.case).update(value_text="Удаленный кейс")
        self.assertFalse(self.preview().data["can_apply"])
        self.link.field_values.filter(field=self.case).delete()
        self.assertFalse(self.preview().data["can_apply"])
        type(self.program).objects.filter(pk=self.program.pk).update(
            legacy_team_min_size=None, is_competitive=False
        )
        self.assertFalse(self.preview().data["can_apply"])

    def test_case_change_preserves_scores_and_only_removes_incompatible_unscored_assignments(
        self,
    ):
        criterion = Criteria.objects.create(
            partner_program=self.program,
            name="Баллы",
            type="int",
            min_value=0,
            max_value=10,
        )
        scored, incompatible, compatible = [
            create_rate_expert(program=self.program) for _ in range(3)
        ]
        for user in (scored, incompatible, compatible):
            ExpertCaseScope.objects.create(
                partner_program=self.program,
                expert=user.expert,
                all_cases=False,
                case_names=["Город"] if user == compatible else ["Банк"],
            )
        PartnerProgramProject.objects.filter(pk=self.link.pk).update(submitted=True)
        assignments = [
            ProjectExpertAssignment.objects.create(
                partner_program=self.program,
                project=self.link.project,
                expert=user.expert,
            )
            for user in (scored, incompatible)
        ]
        # Историческое назначение будущего кейса не должно удаляться.
        keep = ProjectExpertAssignment(
            partner_program=self.program,
            project=self.link.project,
            expert=compatible.expert,
        )
        ProjectExpertAssignment.objects.bulk_create([keep])
        score = ProjectScore.objects.create(
            project=self.link.project, criteria=criterion, user=scored, value="7"
        )
        preview = self.preview("change_case", case_name="Город")
        self.assertEqual(preview.data["score_count"], 1)
        self.assertEqual(preview.data["removed_assignments_count"], 1)
        response = self.apply(preview, "change_case", case_name="Город")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.link.field_values.get(field=self.case).value_text, "Город")
        self.assertTrue(ProjectScore.objects.filter(pk=score.pk, value="7").exists())
        self.assertTrue(
            ProjectExpertAssignment.objects.filter(pk=assignments[0].pk).exists()
        )
        self.assertFalse(
            ProjectExpertAssignment.objects.filter(pk=assignments[1].pk).exists()
        )
        self.assertTrue(ProjectExpertAssignment.objects.filter(pk=keep.pk).exists())

    def test_detach_scored_link_preserves_project_team_scores_and_other_program(self):
        member = create_program_member(self.program).user
        collaboration = Collaborator.objects.create(
            project=self.link.project, user=member
        )
        other = create_program_project(
            create_partner_program(), project=self.link.project
        )
        from partner_programs.models import PartnerProgramUserProfile

        own_profile = PartnerProgramUserProfile.objects.get(
            partner_program=self.program, user=self.link.project.leader
        )
        PartnerProgramUserProfile.objects.filter(pk=own_profile.pk).update(
            project=self.link.project
        )
        other_profile = create_program_member(
            other.partner_program,
            user=self.link.project.leader,
            project=self.link.project,
        )
        expert = create_rate_expert(program=self.program)
        criterion = Criteria.objects.create(
            partner_program=self.program,
            name="Баллы",
            type="int",
            min_value=0,
            max_value=10,
        )
        score = ProjectScore.objects.create(
            project=self.link.project, criteria=criterion, user=expert, value="4"
        )
        PartnerProgramProject.objects.filter(pk=self.link.pk).update(submitted=True)
        assignment = ProjectExpertAssignment.objects.create(
            partner_program=self.program, project=self.link.project, expert=expert.expert
        )
        preview = self.preview("detach")
        self.assertEqual(preview.data["score_count"], 1)
        self.assertEqual(self.apply(preview, "detach").status_code, 200)
        self.assertFalse(PartnerProgramProject.objects.filter(pk=self.link.pk).exists())
        self.assertTrue(Project.objects.filter(pk=self.link.project_id).exists())
        self.assertTrue(Collaborator.objects.filter(pk=collaboration.pk).exists())
        self.assertTrue(PartnerProgramProject.objects.filter(pk=other.pk).exists())
        own_profile.refresh_from_db()
        other_profile.refresh_from_db()
        self.assertIsNone(own_profile.project_id)
        self.assertEqual(other_profile.project_id, self.link.project_id)
        self.assertTrue(ProjectScore.objects.filter(pk=score.pk).exists())
        self.assertFalse(
            ProjectExpertAssignment.objects.filter(pk=assignment.pk).exists()
        )
        self.assertFalse(
            PartnerProgramFieldValue.objects.filter(
                program_project_id=self.link.pk
            ).exists()
        )

    def test_permissions_and_program_object_scope(self):
        for actor in (
            None,
            create_user(),
            self.link.project.leader,
            create_rate_expert(program=self.program),
        ):
            self.client.force_authenticate(actor)
            self.assertEqual(self.preview().status_code, 401 if actor is None else 403)
            response = self.client.post(
                self.root + "apply/",
                {"action": "submit", "ids": [self.link.pk], "preview_token": "fake"},
                format="json",
            )
            self.assertEqual(response.status_code, 401 if actor is None else 403)
        self.client.force_authenticate(self.manager)
        foreign = create_program_project(create_partner_program())
        self.assertEqual(self.preview(ids=[foreign.pk]).status_code, 404)
        self.client.force_authenticate(create_user(is_staff=True))
        self.assertTrue(self.preview().data["can_apply"])

    def test_token_binds_actor_action_case_ids_and_current_state(self):
        preview = self.preview("change_case", case_name="Город")
        self.assertEqual(self.apply(preview, "detach").status_code, 409)
        self.assertEqual(
            self.apply(preview, "change_case", case_name="Банк").status_code, 409
        )
        second = self.make_link()
        self.assertEqual(
            self.apply(
                preview, "change_case", ids=[second.pk], case_name="Город"
            ).status_code,
            409,
        )
        other = create_user()
        self.program.managers.add(other)
        self.client.force_authenticate(other)
        self.assertEqual(
            self.apply(preview, "change_case", case_name="Город").status_code, 409
        )
        self.client.force_authenticate(self.manager)
        self.link.field_values.filter(field=self.deck).update(
            value_text="https://example.test/new.pdf"
        )
        self.assertEqual(
            self.apply(preview, "change_case", case_name="Город").status_code, 409
        )
        self.assertEqual(self.link.field_values.get(field=self.case).value_text, "Банк")

    def test_new_score_requires_new_confirmation_and_revoked_manager_is_denied(self):
        preview = self.preview("detach")
        criterion = Criteria.objects.create(
            partner_program=self.program,
            name="Баллы",
            type="int",
            min_value=0,
            max_value=10,
        )
        ProjectScore.objects.create(
            project=self.link.project,
            criteria=criterion,
            user=create_rate_expert(program=self.program),
            value="3",
        )
        self.assertEqual(self.apply(preview, "detach").status_code, 409)
        self.assertTrue(PartnerProgramProject.objects.filter(pk=self.link.pk).exists())
        preview = self.preview("detach")
        self.program.managers.remove(self.manager)
        self.assertEqual(self.apply(preview, "detach").status_code, 403)

    def test_strict_contract_invalid_case_and_multi_project_changes(self):
        self.assertEqual(
            self.preview("change_case", case_name="Нет такого").status_code, 400
        )
        self.assertEqual(self.preview("change_case").status_code, 400)
        self.assertEqual(self.preview("detach", case_name="Банк").status_code, 400)
        self.assertEqual(
            self.preview("detach", ids=[self.link.pk, self.make_link().pk]).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                self.root + "apply/",
                {"action": "submit", "ids": [self.link.pk]},
                format="json",
            ).status_code,
            400,
        )
        preview = self.preview()
        self.assertEqual(
            self.client.post(
                self.root + "apply/",
                {
                    "action": "submit",
                    "ids": [self.link.pk],
                    "preview_token": preview.data["preview_token"] + "bad",
                },
                format="json",
            ).status_code,
            409,
        )

    def test_expired_confirmation_is_rejected(self):
        with patch("django.core.signing.TimestampSigner.timestamp", return_value="0"):
            preview = self.preview("detach")
        self.assertEqual(self.apply(preview, "detach").status_code, 409)
        self.assertTrue(PartnerProgramProject.objects.filter(pk=self.link.pk).exists())

    def test_malformed_body_unknown_fields_and_get_do_not_mutate(self):
        for body in (
            [{"action": "submit"}],
            {"action": "submit", "ids": [self.link.pk], "force": True},
        ):
            self.assertEqual(
                self.client.post(self.root + "preview/", body, format="json").status_code,
                400,
            )
        self.assertEqual(self.client.get(self.root + "apply/").status_code, 405)
        self.link.refresh_from_db()
        self.assertFalse(self.link.submitted)

    def test_bulk_checks_records_beyond_first_page(self):
        links = [self.link] + [self.make_link() for _ in range(24)]
        ids = [link.pk for link in links]
        links[-1].field_values.filter(field=self.deck).delete()
        preview = self.preview(ids=ids)
        self.assertFalse(preview.data["can_apply"])
        self.assertEqual(preview.data["ready_count"], 24)
        self.assertFalse(
            PartnerProgramProject.objects.filter(pk__in=ids, submitted=True).exists()
        )
        PartnerProgramFieldValue.objects.create(
            program_project=links[-1],
            field=self.deck,
            value_text="https://example.test/deck.pdf",
        )
        preview = self.preview(ids=ids)
        self.assertEqual(self.apply(preview, ids=ids).data["changed_count"], 25)


class ProjectActionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.manager = create_user()
        self.program = create_partner_program(is_competitive=True)
        self.program.managers.add(self.manager)
        self.member = create_program_member(self.program)
        self.link = create_program_project(
            self.program, project=create_project(leader=self.member.user)
        )

    @skipUnlessDBFeature("has_select_for_no_key_update")
    def test_score_commits_while_project_locked_and_requires_fresh_confirmation(self):
        expert = create_rate_expert(program=self.program)
        criterion = Criteria.objects.create(
            partner_program=self.program,
            name="Баллы",
            type="int",
            min_value=0,
            max_value=10,
        )
        body = {"action": "detach", "ids": [self.link.pk]}
        preview = preview_action(self.program.pk, self.manager, body)
        program_locked, project_locked = Event(), Event()

        def score():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '3s'")
                    type(self.program).objects.select_for_update().get(pk=self.program.pk)
                    program_locked.set()
                    self.assertTrue(project_locked.wait(timeout=5))
                    ProjectScore.objects.create(
                        project=self.link.project,
                        criteria=criterion,
                        user=expert,
                        value="3",
                    )
                return "scored"
            finally:
                close_old_connections()

        def apply():
            close_old_connections()

            def notice(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                if 'FROM "projects_project"' in sql and " FOR " in sql:
                    project_locked.set()
                return result

            try:
                self.assertTrue(program_locked.wait(timeout=5))
                with connection.execute_wrapper(notice):
                    try:
                        apply_action(
                            self.program.pk,
                            self.manager,
                            {**body, "preview_token": preview["preview_token"]},
                        )
                        return "applied"
                    except ActionConflict:
                        return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            scoring, applying = pool.submit(score), pool.submit(apply)
            self.assertEqual(scoring.result(timeout=10), "scored")
            self.assertEqual(applying.result(timeout=10), "conflict")
        self.assertTrue(PartnerProgramProject.objects.filter(pk=self.link.pk).exists())
        self.assertTrue(ProjectScore.objects.filter(project=self.link.project).exists())

    @skipUnlessDBFeature("has_select_for_no_key_update")
    def test_simultaneous_submission_uses_confirmation_only_once(self):
        body = {"action": "submit", "ids": [self.link.pk]}
        preview = preview_action(self.program.pk, self.manager, body)
        barrier = Barrier(2)

        def apply():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return apply_action(
                        self.program.pk,
                        self.manager,
                        {**body, "preview_token": preview["preview_token"]},
                    )["changed_count"]
                except ActionConflict:
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: apply(), range(2)))
        self.assertCountEqual(results, [1, "conflict"])
