from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from invites.models import Invite
from invites.tests import test_invite_integrity as integrity
from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.services.exports import _calc_team_size
from partner_programs.tests.helpers import project_apply_payload
from partner_programs.tests.helpers import create_program_field
from projects import team_policy
from projects.models import Collaborator, Project
from projects.tests.helpers import (
    add_program_member,
    create_collaborator,
    create_partner_program,
    create_project,
    create_user,
)
from vacancy.tests.helpers import create_vacancy, create_vacancy_response


class TeamPolicyFixtures:
    def team(self, program=None):
        program = program or create_partner_program(is_competitive=True)
        leader = create_user()
        add_program_member(program, leader)
        project = create_project(leader=leader)
        link = PartnerProgramProject.objects.create(
            project=project, partner_program=program
        )
        return project, link

    def registered(self, program):
        user = create_user()
        add_program_member(program, user)
        return user

    def request(self, actor, method, url, data=None):
        client = APIClient()
        client.force_authenticate(actor)
        return getattr(client, method)(url, data or {}, format="json")

    def invite(self, project, user, **data):
        response = self.request(
            project.leader,
            "post",
            "/invites/",
            {"project": project.pk, "user": user.pk, "role": "Member", **data},
        )
        self.assertEqual(response.status_code, 201, response.data)
        return Invite.objects.get(pk=response.data["id"])

    def submit(self, project, link):
        return self.request(
            project.leader,
            "post",
            f"/programs/partner-program-projects/{link.pk}/submit/",
        )

    def assert_conflict(self, response, code):
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], code)


class CompetitiveTeamPolicyTests(TeamPolicyFixtures, TestCase):
    def setUp(self):
        self.project, self.link = self.team()
        self.program = self.link.partner_program

    def test_freeze_all_legacy_roster_operations(self):
        member = self.registered(self.program)
        create_collaborator(self.project, user=member)
        recipient = self.registered(self.program)
        pending = self.invite(self.project, recipient)
        self.assertEqual(self.submit(self.project, self.link).status_code, 200)
        requests = [
            (
                self.project.leader,
                "post",
                "/invites/",
                {"project": self.project.pk, "user": recipient.pk},
            ),
            (self.project.leader, "patch", f"/invites/{pending.pk}/", {"role": "New"}),
            (recipient, "post", f"/invites/{pending.pk}/accept/", {}),
            (
                self.project.leader,
                "delete",
                f"/projects/{self.project.pk}/collaborators/?id={member.pk}",
                {},
            ),
            (member, "delete", f"/projects/{self.project.pk}/collaborators/leave/", {}),
            (
                self.project.leader,
                "patch",
                f"/projects/{self.project.pk}/collaborators/{member.pk}/switch-leader/",
                {},
            ),
            (
                self.project.leader,
                "post",
                f"/projects/{self.project.pk}/collaborators/",
                {},
            ),
        ]
        for args in requests:
            with self.subTest(method=args[1], url=args[2]):
                self.assert_conflict(self.request(*args), "team_frozen")
        self.assertEqual(
            team_policy.accepted_user_ids(self.project),
            {self.project.leader_id, member.pk},
        )
        pending.refresh_from_db()
        self.assertIsNone(pending.is_accepted)

    def test_decline_and_revoke_pending_are_allowed_after_submission(self):
        recipient = self.registered(self.program)
        decline = self.invite(self.project, recipient)
        revoke = self.invite(self.project, self.registered(self.program))
        self.assertEqual(self.submit(self.project, self.link).status_code, 200)
        self.assertEqual(
            self.request(
                recipient, "post", f"/invites/{decline.pk}/decline/"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.request(
                self.project.leader, "delete", f"/invites/{revoke.pk}/"
            ).status_code,
            204,
        )
        self.assertFalse(Invite.objects.filter(pk=revoke.pk).exists())

    def test_collaborator_and_leader_cannot_accept_other_team(self):
        other, _ = self.team(self.program)
        user = self.registered(self.program)
        pending = self.invite(other, user)
        create_collaborator(self.project, user=user)
        self.assert_conflict(
            self.request(user, "post", f"/invites/{pending.pk}/accept/"),
            "already_in_program_team",
        )
        self.assert_conflict(
            self.request(
                other.leader,
                "post",
                "/invites/",
                {"project": other.pk, "user": self.project.leader_id},
            ),
            "already_in_program_team",
        )

    def test_collaborator_cannot_apply_or_create_own_program_project(self):
        user = self.registered(self.program)
        create_collaborator(self.project, user=user)
        before = Project.objects.count()
        self.assert_conflict(
            self.request(
                user,
                "post",
                f"/programs/{self.program.pk}/projects/apply/",
                project_apply_payload(),
            ),
            "already_in_program_team",
        )
        self.assert_conflict(
            self.request(
                user,
                "post",
                "/projects/",
                {"name": "Own", "partner_program_id": self.program.pk},
            ),
            "already_in_program_team",
        )
        self.assertEqual(Project.objects.count(), before)

    def test_membership_in_different_program_is_allowed(self):
        other, other_link = self.team()
        user = self.registered(self.program)
        create_collaborator(self.project, user=user)
        add_program_member(other_link.partner_program, user)
        pending = self.invite(other, user)
        self.assertEqual(
            self.request(user, "post", f"/invites/{pending.pk}/accept/").status_code, 200
        )

    def test_finished_program_does_not_enforce_exclusivity(self):
        other, _ = self.team(self.program)
        self.program.datetime_finished = timezone.now() - timezone.timedelta(seconds=1)
        self.program.save(update_fields=["datetime_finished"])
        pending = self.invite(other, self.project.leader)
        self.assertEqual(
            self.request(
                self.project.leader, "post", f"/invites/{pending.pk}/accept/"
            ).status_code,
            200,
        )

    def test_minimum_only_on_submit_pending_not_counted(self):
        self.program.legacy_team_min_size = 2
        self.program.save(update_fields=["legacy_team_min_size"])
        recipient = self.registered(self.program)
        pending = self.invite(self.project, recipient)
        self.assertTrue(self.project.draft)
        self.assert_conflict(self.submit(self.project, self.link), "team_min_size")
        self.assertEqual(
            self.request(recipient, "post", f"/invites/{pending.pk}/accept/").status_code,
            200,
        )
        self.assertEqual(self.submit(self.project, self.link).status_code, 200)

    def test_maximum_reserves_pending_capacity_and_counts_leader_once(self):
        self.program.legacy_team_max_size = 2
        self.program.save(update_fields=["legacy_team_max_size"])
        first = self.registered(self.program)
        second = self.registered(self.program)
        pending = self.invite(self.project, first)
        self.assertEqual(_calc_team_size(self.project), 1)
        self.assert_conflict(
            self.request(
                self.project.leader,
                "post",
                "/invites/",
                {"project": self.project.pk, "user": second.pk},
            ),
            "team_max_size",
        )
        self.assertEqual(
            self.request(first, "post", f"/invites/{pending.pk}/accept/").status_code, 200
        )
        self.assertEqual(_calc_team_size(self.project), 2)
        self.assertEqual(self.submit(self.project, self.link).status_code, 200)

    def test_accept_checks_current_maximum_after_configuration_changed(self):
        recipient = self.registered(self.program)
        pending = self.invite(self.project, recipient)
        self.program.legacy_team_max_size = 1
        self.program.save(update_fields=["legacy_team_max_size"])
        self.assert_conflict(
            self.request(recipient, "post", f"/invites/{pending.pk}/accept/"),
            "team_max_size",
        )

    def test_submission_validates_current_memberships_and_maximum(self):
        member = self.registered(self.program)
        create_collaborator(self.project, user=member)
        membership = PartnerProgramUserProfile.objects.get(
            partner_program=self.program, user=member
        )
        membership.delete()
        self.assert_conflict(self.submit(self.project, self.link), "not_program_member")
        add_program_member(self.program, member)
        self.program.legacy_team_max_size = 1
        self.program.save(update_fields=["legacy_team_max_size"])
        self.assert_conflict(self.submit(self.project, self.link), "team_max_size")

    def test_both_null_preserve_solo_submission(self):
        self.assertEqual(self.submit(self.project, self.link).status_code, 200)

    def test_program_bounds_validate_independent_nulls_and_db_order(self):
        for minimum, maximum in ((None, 1), (2, None), (None, None), (2, 2)):
            self.program.legacy_team_min_size = minimum
            self.program.legacy_team_max_size = maximum
            self.program.clean()
        self.program.legacy_team_max_size = 1
        with self.assertRaises(ValidationError):
            self.program.clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(self.program).objects.filter(pk=self.program.pk).update(
                legacy_team_min_size=2, legacy_team_max_size=1
            )

    def test_model_and_api_submission_require_current_required_fields(self):
        field = create_program_field(self.program, is_required=True)
        self.link.submitted = True
        with self.assertRaisesMessage(ValidationError, "обязательные поля"):
            self.link.save(update_fields=["submitted"])
        response = self.submit(self.project, self.link)
        self.assertEqual(response.status_code, 400)
        self.link.refresh_from_db()
        self.assertFalse(self.link.submitted)
        field.delete()
        self.assertEqual(self.submit(self.project, self.link).status_code, 200)

    def test_clone_same_program_rolls_back_project_and_copied_roster(self):
        source = create_project(leader=self.project.leader)
        before = Project.objects.count()
        response = self.request(
            self.project.leader,
            "post",
            "/projects/assign-to-program/",
            {
                "project_id": source.pk,
                "partner_program_id": self.program.pk,
            },
        )
        self.assert_conflict(response, "already_in_program_team")
        self.assertEqual(Project.objects.count(), before)

    def test_bind_checks_every_existing_member_and_rolls_back(self):
        other = create_project()
        add_program_member(self.program, other.leader)
        create_collaborator(other, user=self.project.leader)
        response = self.request(
            other.leader,
            "patch",
            f"/projects/{other.pk}/",
            {
                "partner_program_id": self.program.pk,
            },
        )
        self.assert_conflict(response, "already_in_program_team")
        self.assertFalse(other.program_links.exists())

    def test_pending_edit_after_membership_removal_is_controlled(self):
        user = self.registered(self.program)
        pending = self.invite(self.project, user)
        PartnerProgramUserProfile.objects.filter(
            user=user, partner_program=self.program
        ).delete()
        self.assert_conflict(
            self.request(
                self.project.leader,
                "patch",
                f"/invites/{pending.pk}/",
                {"role": "Changed"},
            ),
            "not_program_member",
        )

    def test_vacancy_accept_checks_exclusivity(self):
        other, _ = self.team(self.program)
        vacancy = create_vacancy(project=self.project)
        response = create_vacancy_response(vacancy=vacancy, user=other.leader)
        self.assert_conflict(
            self.request(
                self.project.leader, "post", f"/vacancies/responses/{response.pk}/accept/"
            ),
            "already_in_program_team",
        )
        response.refresh_from_db()
        self.assertIsNone(response.is_approved)

    def test_switch_leader_rechecks_membership(self):
        member = self.registered(self.program)
        create_collaborator(self.project, user=member)
        PartnerProgramUserProfile.objects.filter(
            user=member, partner_program=self.program
        ).delete()
        self.assert_conflict(
            self.request(
                self.project.leader,
                "patch",
                f"/projects/{self.project.pk}/collaborators/{member.pk}/switch-leader/",
            ),
            "not_program_member",
        )

    def test_explicit_other_link_cannot_bypass_submitted_shared_team(self):
        other_program = create_partner_program(is_competitive=True)
        add_program_member(other_program, self.project.leader)
        other_link = PartnerProgramProject.objects.create(
            project=self.project, partner_program=other_program
        )
        user = self.registered(self.program)
        add_program_member(other_program, user)
        self.assertEqual(self.submit(self.project, self.link).status_code, 200)
        self.assert_conflict(
            self.request(
                self.project.leader,
                "post",
                "/invites/",
                {
                    "project": self.project.pk,
                    "user": user.pk,
                    "program_link_id": other_link.pk,
                },
            ),
            "team_frozen",
        )

    def test_multi_link_requires_explicit_context_and_stores_link(self):
        other_program = create_partner_program(is_competitive=True)
        add_program_member(other_program, self.project.leader)
        other_link = PartnerProgramProject.objects.create(
            project=self.project, partner_program=other_program
        )
        user = self.registered(self.program)
        add_program_member(other_program, user)
        payload = {"project": self.project.pk, "user": user.pk}
        self.assert_conflict(
            self.request(self.project.leader, "post", "/invites/", payload),
            "program_context_required",
        )
        pending = self.invite(self.project, user, program_link_id=other_link.pk)
        self.assertEqual(pending.program_link_id, other_link.pk)
        self.assertEqual(
            self.request(user, "post", f"/invites/{pending.pk}/accept/").status_code, 200
        )

    def test_explicit_link_from_other_project_is_rejected(self):
        other, link = self.team()
        response = self.request(
            self.project.leader,
            "post",
            "/invites/",
            {
                "project": self.project.pk,
                "user": self.registered(self.program).pk,
                "program_link_id": link.pk,
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data["code"], "invalid_program_context")

    def test_ordinary_project_needs_no_program_context(self):
        project = create_project()
        user = create_user()
        pending = self.invite(project, user)
        self.assertIsNone(pending.program_link_id)
        self.assertEqual(
            self.request(user, "post", f"/invites/{pending.pk}/accept/").status_code, 200
        )

    def test_vacancy_accept_cannot_bypass_freeze(self):
        candidate = self.registered(self.program)
        vacancy = create_vacancy(project=self.project)
        response = create_vacancy_response(vacancy=vacancy, user=candidate)
        self.assertEqual(self.submit(self.project, self.link).status_code, 200)
        self.assert_conflict(
            self.request(
                self.project.leader, "post", f"/vacancies/responses/{response.pk}/accept/"
            ),
            "team_frozen",
        )
        response.refresh_from_db()
        self.assertIsNone(response.is_approved)

    def test_model_member_change_cannot_bypass_freeze(self):
        member = self.registered(self.program)
        row = create_collaborator(self.project, user=member)
        self.assertEqual(self.submit(self.project, self.link).status_code, 200)
        row.role = "Changed"
        with self.assertRaises(ValidationError):
            row.save()
        with self.assertRaises(ValidationError):
            row.delete()
        row.refresh_from_db()
        self.assertNotEqual(row.role, "Changed")

    def test_recommendation_candidates_are_actionable(self):
        from users.models import CustomUser
        from projects.team_policy import actionable_users

        eligible = self.registered(self.program)
        pending_user = self.registered(self.program)
        self.invite(self.project, pending_user)
        other, _ = self.team(self.program)
        user_ids = set(
            actionable_users(self.project, CustomUser.objects.all()).values_list(
                "pk", flat=True
            )
        )
        self.assertIn(eligible.pk, user_ids)
        self.assertNotIn(pending_user.pk, user_ids)
        self.assertNotIn(other.leader_id, user_ids)
        self.assertNotIn(self.project.leader_id, user_ids)
        self.assertNotIn(create_user().pk, user_ids)


@skipUnlessDBFeature("has_select_for_update")
class CompetitiveTeamConcurrencyTests(TeamPolicyFixtures, TransactionTestCase):
    race = integrity.InviteConcurrencyTests.race

    def test_concurrent_invites_reserve_only_one_remaining_place(self):
        project, link = self.team()
        program = link.partner_program
        program.legacy_team_max_size = 2
        program.save(update_fields=["legacy_team_max_size"])
        users = [self.registered(program), self.registered(program)]
        statuses = self.race(
            *[
                (
                    project.leader,
                    "post",
                    "/invites/",
                    {"project": project.pk, "user": user.pk},
                )
                for user in users
            ]
        )
        self.assertEqual(sorted(statuses), [201, 409])
        self.assertEqual(len(team_policy.reserved_user_ids(project)), 2)

    def test_accept_into_two_teams_only_one_succeeds(self):
        project, link = self.team()
        other, _ = self.team(link.partner_program)
        user = self.registered(link.partner_program)
        first, second = self.invite(project, user), self.invite(other, user)
        statuses = self.race(
            (user, "post", f"/invites/{first.pk}/accept/", {}),
            (user, "post", f"/invites/{second.pk}/accept/", {}),
        )
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(Collaborator.objects.filter(user=user).count(), 1)

    def test_submit_accept_share_final_roster(self):
        project, link = self.team()
        user = self.registered(link.partner_program)
        pending = self.invite(project, user)
        snapshots = []
        original = team_policy.validate_submission_team

        def capture(*args):
            result = original(*args)
            snapshots.append(result)
            return result

        with patch.object(team_policy, "validate_submission_team", side_effect=capture):
            statuses = self.race(
                (
                    project.leader,
                    "post",
                    f"/programs/partner-program-projects/{link.pk}/submit/",
                    {},
                ),
                (user, "post", f"/invites/{pending.pk}/accept/", {}),
            )
        self.assertEqual(statuses[0], 200)
        self.assertIn(statuses[1], (200, 409))
        self.assertEqual(team_policy.accepted_user_ids(project), snapshots[-1])

    def test_submit_remove_share_final_roster(self):
        project, link = self.team()
        member = self.registered(link.partner_program)
        create_collaborator(project, user=member)
        snapshots = []
        original = team_policy.validate_submission_team

        def capture(*args):
            result = original(*args)
            snapshots.append(result)
            return result

        with patch.object(team_policy, "validate_submission_team", side_effect=capture):
            statuses = self.race(
                (
                    project.leader,
                    "post",
                    f"/programs/partner-program-projects/{link.pk}/submit/",
                    {},
                ),
                (
                    project.leader,
                    "delete",
                    f"/projects/{project.pk}/collaborators/?id={member.pk}",
                    {},
                ),
            )
        self.assertEqual(statuses[0], 200)
        self.assertIn(statuses[1], (204, 409))
        self.assertEqual(team_policy.accepted_user_ids(project), snapshots[-1])
