from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    Application,
    PartnerProgram,
    Submission,
    TeamInvite,
    TeamMember,
)
from partner_programs.services.application_team import create_or_get_application
from partner_programs.services.team_invites import create_team_invite
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)
from partner_programs.throttling import TeamInviteMutationScopedRateThrottle


class TeamInviteAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.captain = create_user(prefix="invite-api-captain")
        self.target = create_user(prefix="invite-api-target")
        self.member_user = create_user(prefix="invite-api-member")
        self.manager = create_user(prefix="invite-api-manager")
        self.staff = create_user(prefix="invite-api-staff", is_staff=True)
        self.outsider = create_user(prefix="invite-api-outsider")
        self.program = create_partner_program(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=2,
            team_max_size=6,
        )
        self.program.managers.add(self.manager)
        for user in (self.captain, self.target, self.member_user):
            create_program_member(self.program, user=user)
        self.application = create_or_get_application(
            program=self.program,
            user=self.captain,
            created_by=self.captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            team_name="API приглашения",
        ).application
        self.team = self.application.team
        self.member = TeamMember.objects.create(
            team=self.team,
            user=self.member_user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
            invited_by=self.captain,
        )

    @property
    def list_url(self):
        return f"/applications/{self.application.pk}/team/invites/"

    @staticmethod
    def action_url(invite, action):
        return f"/team-invites/{invite.pk}/{action}/"

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def create_target(self, prefix="invite-api-extra"):
        user = create_user(prefix=prefix)
        create_program_member(self.program, user=user)
        return user

    def create_invite(self, *, target=None, actor=None):
        return create_team_invite(
            team=self.team,
            actor=actor or self.captain,
            target=target or self.target,
        ).invite

    def test_anonymous_user_cannot_use_invite_endpoints(self):
        invite = self.create_invite()

        self.assertEqual(self.client.get(self.list_url).status_code, 401)
        self.assertEqual(
            self.client.post(
                self.list_url,
                {"user_id": self.target.pk},
                format="json",
            ).status_code,
            401,
        )
        self.assertEqual(self.client.get("/team-invites/my/").status_code, 401)
        for action in ("accept", "decline", "revoke"):
            with self.subTest(action=action):
                self.assertEqual(
                    self.client.post(self.action_url(invite, action)).status_code,
                    401,
                )

    def test_captain_and_staff_can_list_but_member_manager_cannot(self):
        self.create_invite()
        for user in (self.captain, self.staff):
            self.authenticate(user)
            with self.subTest(allowed=user):
                self.assertEqual(self.client.get(self.list_url).status_code, 200)

        for user in (self.member_user, self.manager):
            self.authenticate(user)
            with self.subTest(forbidden=user):
                self.assertEqual(self.client.get(self.list_url).status_code, 403)

        self.authenticate(self.outsider)
        self.assertEqual(self.client.get(self.list_url).status_code, 404)

    def test_create_is_idempotent_and_exposes_only_safe_user_fields(self):
        self.authenticate(self.captain)
        first = self.client.post(
            self.list_url,
            {"user_id": self.target.pk},
            format="json",
        )
        second = self.client.post(
            self.list_url,
            {"user_id": self.target.pk},
            format="json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(
            set(first.data["user"]),
            {"id", "display_name", "avatar"},
        )
        self.assertEqual(
            set(first.data["invited_by"]),
            {"id", "display_name", "avatar"},
        )
        self.assertNotIn("email", first.data["user"])
        self.assertFalse(
            TeamMember.objects.filter(team=self.team, user=self.target).exists()
        )

    def test_member_and_manager_cannot_create_outsider_gets_hidden_404(self):
        for user in (self.member_user, self.manager):
            self.authenticate(user)
            with self.subTest(user=user):
                self.assertEqual(
                    self.client.post(
                        self.list_url,
                        {"user_id": self.target.pk},
                        format="json",
                    ).status_code,
                    403,
                )

        self.authenticate(self.outsider)
        self.assertEqual(
            self.client.post(
                self.list_url,
                {"user_id": self.target.pk},
                format="json",
            ).status_code,
            404,
        )

    def test_staff_can_create_invite(self):
        self.authenticate(self.staff)

        response = self.client.post(
            self.list_url,
            {"user_id": self.target.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["invited_by"]["id"], self.staff.pk)

    def test_unknown_target_and_domain_state_errors_return_400(self):
        self.authenticate(self.captain)
        self.assertEqual(
            self.client.post(
                self.list_url,
                {"user_id": 99999999},
                format="json",
            ).status_code,
            400,
        )

        self.program.team_max_size = 2
        self.program.save(update_fields=["team_max_size"])
        self.assertEqual(
            self.client.post(
                self.list_url,
                {"user_id": self.target.pk},
                format="json",
            ).status_code,
            400,
        )

    def test_my_invites_returns_only_current_user_pending_first(self):
        resolved = TeamInvite.objects.create(
            team=self.team,
            user=self.target,
            invited_by=self.captain,
            status=TeamInvite.STATUS_DECLINED,
            resolved_at=timezone.now(),
        )
        pending = self.create_invite()
        other_target = self.create_target()
        self.create_invite(target=other_target)
        self.authenticate(self.target)

        response = self.client.get("/team-invites/my/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data], [pending.pk, resolved.pk])
        self.assertEqual(response.data[0]["application_id"], self.application.pk)
        self.assertEqual(response.data[0]["program"]["id"], self.program.pk)
        self.assertEqual(response.data[0]["captain"]["id"], self.captain.pk)
        self.assertTrue(response.data[0]["can_accept"])
        self.assertTrue(response.data[0]["can_decline"])

    def test_pending_invite_does_not_grant_access_but_accept_does(self):
        invite = self.create_invite()
        submission = Submission.objects.create(
            application=self.application,
            program=self.program,
            submitted_by=self.captain,
            title="Закрытое решение",
        )
        application_url = f"/applications/{self.application.pk}/"
        team_url = f"/applications/{self.application.pk}/team/"
        submission_url = f"/submissions/{submission.pk}/"
        self.authenticate(self.target)

        self.assertEqual(self.client.get(application_url).status_code, 404)
        self.assertEqual(self.client.get(team_url).status_code, 404)
        self.assertEqual(self.client.get(submission_url).status_code, 404)

        accepted = self.client.post(self.action_url(invite, "accept"), {}, format="json")

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.data["status"], TeamInvite.STATUS_ACCEPTED)
        self.assertEqual(self.client.get(application_url).status_code, 200)
        self.assertEqual(self.client.get(team_url).status_code, 200)
        self.assertEqual(self.client.get(submission_url).status_code, 200)
        self.assertEqual(
            self.client.patch(application_url, {"form_data": {}}, format="json").status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(team_url, {"name": "Нельзя"}, format="json").status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(submission_url, {"title": "Нельзя"}, format="json").status_code,
            403,
        )

    def test_accept_decline_and_revoke_actions(self):
        accepted_invite = self.create_invite()
        self.authenticate(self.target)
        accepted = self.client.post(
            self.action_url(accepted_invite, "accept"),
            {},
            format="json",
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.data["status"], TeamInvite.STATUS_ACCEPTED)

        decline_target = self.create_target(prefix="invite-api-decline")
        decline_invite = self.create_invite(target=decline_target)
        self.authenticate(decline_target)
        declined = self.client.post(
            self.action_url(decline_invite, "decline"),
            {},
            format="json",
        )
        self.assertEqual(declined.status_code, 200)
        self.assertEqual(declined.data["status"], TeamInvite.STATUS_DECLINED)
        self.assertFalse(
            TeamMember.objects.filter(team=self.team, user=decline_target).exists()
        )

        revoke_target = self.create_target(prefix="invite-api-revoke")
        revoke_invite = self.create_invite(target=revoke_target)
        self.authenticate(self.captain)
        revoked = self.client.post(
            self.action_url(revoke_invite, "revoke"),
            {},
            format="json",
        )
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(revoked.data["status"], TeamInvite.STATUS_REVOKED)

    def test_action_permission_boundaries_are_404_or_403(self):
        invite = self.create_invite()
        self.authenticate(self.outsider)
        self.assertEqual(
            self.client.post(self.action_url(invite, "accept")).status_code,
            404,
        )

        self.authenticate(self.captain)
        self.assertEqual(
            self.client.post(self.action_url(invite, "accept")).status_code,
            403,
        )

        self.authenticate(self.target)
        declined = self.client.post(self.action_url(invite, "decline"))
        self.assertEqual(declined.status_code, 200)
        self.assertEqual(
            self.client.post(self.action_url(invite, "accept")).status_code,
            400,
        )
        self.assertEqual(self.client.post("/team-invites/999999/accept/").status_code, 404)

    def test_invite_mutations_are_blocked_after_application_submit(self):
        accept_target = self.target
        decline_target = self.create_target(prefix="invite-api-locked-decline")
        revoke_target = self.create_target(prefix="invite-api-locked-revoke")
        accept_invite = self.create_invite(target=accept_target)
        decline_invite = self.create_invite(target=decline_target)
        revoke_invite = self.create_invite(target=revoke_target)
        create_target = self.create_target(prefix="invite-api-locked-create")
        self.application.status = Application.STATUS_SUBMITTED
        self.application.save(update_fields=["status", "updated_at"])

        self.authenticate(self.captain)
        self.assertEqual(
            self.client.post(
                self.list_url,
                {"user_id": create_target.pk},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(self.action_url(revoke_invite, "revoke")).status_code,
            400,
        )
        self.authenticate(accept_target)
        self.assertEqual(
            self.client.post(self.action_url(accept_invite, "accept")).status_code,
            400,
        )
        self.authenticate(decline_target)
        self.assertEqual(
            self.client.post(self.action_url(decline_invite, "decline")).status_code,
            400,
        )

    @patch.object(TeamInviteMutationScopedRateThrottle, "rate", "1/min")
    def test_create_has_own_throttle_and_get_is_not_throttled(self):
        self.authenticate(self.captain)
        first_target = self.target
        second_target = self.create_target(prefix="invite-api-throttle-create")

        self.assertEqual(
            self.client.post(
                self.list_url,
                {"user_id": first_target.pk},
                format="json",
            ).status_code,
            201,
        )
        self.assertEqual(
            self.client.post(
                self.list_url,
                {"user_id": second_target.pk},
                format="json",
            ).status_code,
            429,
        )
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.list_url).status_code, 200)

    @patch.object(TeamInviteMutationScopedRateThrottle, "rate", "1/min")
    def test_accept_decline_and_revoke_have_separate_throttle_scopes(self):
        accept_invite = self.create_invite()
        self.authenticate(self.target)
        self.assertEqual(
            self.client.post(self.action_url(accept_invite, "accept")).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(self.action_url(accept_invite, "accept")).status_code,
            429,
        )

        decline_target = self.create_target(prefix="invite-api-throttle-decline")
        decline_invite = self.create_invite(target=decline_target)
        self.authenticate(decline_target)
        self.assertEqual(
            self.client.post(self.action_url(decline_invite, "decline")).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(self.action_url(decline_invite, "decline")).status_code,
            429,
        )

        revoke_target = self.create_target(prefix="invite-api-throttle-revoke")
        revoke_invite = self.create_invite(target=revoke_target)
        self.authenticate(self.captain)
        self.assertEqual(
            self.client.post(self.action_url(revoke_invite, "revoke")).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(self.action_url(revoke_invite, "revoke")).status_code,
            429,
        )
