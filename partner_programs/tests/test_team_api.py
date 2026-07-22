from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    Application,
    PartnerProgram,
    Submission,
    TeamMember,
)
from partner_programs.services.application_team import create_or_get_application
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)
from partner_programs.throttling import TeamMutationScopedRateThrottle


class TeamAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.captain = create_user(prefix="team-api-captain")
        self.member_user = create_user(prefix="team-api-member")
        self.manager = create_user(prefix="team-api-manager")
        self.staff = create_user(prefix="team-api-staff", is_staff=True)
        self.outsider = create_user(prefix="team-api-outsider")
        self.program = create_partner_program(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=2,
            team_max_size=5,
        )
        self.program.managers.add(self.manager)
        create_program_member(self.program, user=self.captain)
        create_program_member(self.program, user=self.member_user)
        self.application = create_or_get_application(
            program=self.program,
            user=self.captain,
            created_by=self.captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            team_name="API команда",
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
    def team_url(self):
        return f"/applications/{self.application.pk}/team/"

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def add_member(self, *, status=TeamMember.STATUS_ACCEPTED, register=True):
        user = create_user(prefix="team-api-extra")
        if register:
            create_program_member(self.program, user=user)
        return TeamMember.objects.create(
            team=self.team,
            user=user,
            role=TeamMember.ROLE_MEMBER,
            status=status,
            invited_by=self.captain,
        )

    def test_unauthenticated_user_cannot_read_team(self):
        response = self.client.get(self.team_url)
        self.assertEqual(response.status_code, 401)

    def test_captain_member_manager_and_staff_can_read_team(self):
        for user in (self.captain, self.member_user, self.manager, self.staff):
            self.authenticate(user)
            with self.subTest(user=user):
                response = self.client.get(self.team_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["id"], self.team.pk)

    def test_outsider_and_historical_members_cannot_read_team(self):
        self.authenticate(self.outsider)
        self.assertEqual(self.client.get(self.team_url).status_code, 404)

        for membership_status in (
            TeamMember.STATUS_INVITED,
            TeamMember.STATUS_DECLINED,
            TeamMember.STATUS_REMOVED,
            TeamMember.STATUS_LEFT,
        ):
            self.member.status = membership_status
            self.member.save(update_fields=["status", "updated_at"])
            self.authenticate(self.member_user)
            with self.subTest(status=membership_status):
                self.assertEqual(self.client.get(self.team_url).status_code, 404)

    def test_individual_application_has_no_team_endpoint(self):
        owner = create_user(prefix="individual-team-api")
        individual_program = create_partner_program()
        application = Application.objects.create(
            program=individual_program,
            user=owner,
            created_by=owner,
        )
        self.authenticate(owner)

        response = self.client.get(f"/applications/{application.pk}/team/")

        self.assertEqual(response.status_code, 404)

    def test_team_response_is_sorted_and_does_not_expose_private_user_data(self):
        invited = self.add_member(status=TeamMember.STATUS_INVITED, register=False)
        self.authenticate(self.captain)

        response = self.client.get(self.team_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["application_id"], self.application.pk)
        self.assertEqual(response.data["program_id"], self.program.pk)
        self.assertEqual(response.data["team_min_size"], 2)
        self.assertEqual(response.data["team_max_size"], 5)
        self.assertEqual(response.data["accepted_members_count"], 2)
        self.assertEqual(response.data["current_user_role"], TeamMember.ROLE_CAPTAIN)
        member_ids = [item["id"] for item in response.data["members"]]
        self.assertEqual(member_ids[0], self.team.members.get(role="captain").pk)
        self.assertEqual(member_ids[-1], invited.pk)
        for item in response.data["members"]:
            self.assertEqual(
                set(item["user"]),
                {"id", "display_name", "avatar"},
            )
            self.assertNotIn("email", item["user"])

    def test_capability_flags_follow_role_and_draft_state(self):
        expected = {
            self.captain: (True, True, False),
            self.member_user: (False, False, True),
            self.manager: (False, False, False),
            self.staff: (True, True, False),
        }
        for user, flags in expected.items():
            self.authenticate(user)
            response = self.client.get(self.team_url)
            with self.subTest(user=user):
                self.assertEqual(
                    (
                        response.data["can_edit"],
                        response.data["can_manage_members"],
                        response.data["can_leave"],
                    ),
                    flags,
                )

    def test_captain_can_rename_team_and_only_name_is_writable(self):
        self.authenticate(self.captain)
        response = self.client.patch(
            self.team_url,
            {"name": "Новое имя"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Новое имя")

        blocked = self.client.patch(
            self.team_url,
            {
                "name": "Попытка",
                "captain": self.member_user.pk,
                "application": 999,
                "members": [],
            },
            format="json",
        )
        self.assertEqual(blocked.status_code, 400)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Новое имя")
        self.assertEqual(self.team.captain, self.captain)

    def test_member_and_manager_cannot_rename_team(self):
        for user in (self.member_user, self.manager):
            self.authenticate(user)
            with self.subTest(user=user):
                response = self.client.patch(
                    self.team_url,
                    {"name": "Запрещено"},
                    format="json",
                )
                self.assertEqual(response.status_code, 403)

    def test_rename_is_blocked_after_deadline_or_submit(self):
        self.authenticate(self.captain)
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_application_ends=(
                timezone.now() - timezone.timedelta(seconds=1)
            )
        )
        self.assertEqual(
            self.client.patch(
                self.team_url,
                {"name": "Поздно"},
                format="json",
            ).status_code,
            400,
        )

        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_application_ends=None
        )
        Application.objects.filter(pk=self.application.pk).update(
            status=Application.STATUS_SUBMITTED
        )
        self.assertEqual(
            self.client.patch(
                self.team_url,
                {"name": "Отправлено"},
                format="json",
            ).status_code,
            400,
        )

    @patch.object(TeamMutationScopedRateThrottle, "rate", "1/min")
    def test_team_rename_has_scoped_throttle(self):
        self.authenticate(self.captain)
        first = self.client.patch(self.team_url, {"name": "Раз"}, format="json")
        second = self.client.patch(self.team_url, {"name": "Два"}, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_member_can_leave_and_repeat_is_stable_error(self):
        self.authenticate(self.member_user)
        url = f"/applications/{self.application.pk}/team/leave/"
        first = self.client.post(url, {}, format="json")
        second = self.client.post(url, {}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["status"], TeamMember.STATUS_LEFT)
        self.assertEqual(second.status_code, 400)
        self.member.refresh_from_db()
        self.assertIsNotNone(self.member.joined_at)

    def test_captain_cannot_leave_and_member_cannot_leave_after_submit(self):
        self.authenticate(self.captain)
        url = f"/applications/{self.application.pk}/team/leave/"
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)

        Application.objects.filter(pk=self.application.pk).update(
            status=Application.STATUS_SUBMITTED
        )
        self.authenticate(self.member_user)
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)

    def test_captain_can_remove_member_but_member_and_manager_cannot(self):
        url = (
            f"/applications/{self.application.pk}/team/members/"
            f"{self.member.pk}/remove/"
        )
        for user in (self.member_user, self.manager):
            self.authenticate(user)
            with self.subTest(user=user):
                self.assertEqual(
                    self.client.post(url, {}, format="json").status_code,
                    403,
                )

        self.authenticate(self.captain)
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], TeamMember.STATUS_REMOVED)

    def test_remove_rejects_captain_or_member_of_another_team(self):
        captain_member = self.team.members.get(role=TeamMember.ROLE_CAPTAIN)
        self.authenticate(self.captain)
        captain_url = (
            f"/applications/{self.application.pk}/team/members/"
            f"{captain_member.pk}/remove/"
        )
        self.assertEqual(
            self.client.post(captain_url, {}, format="json").status_code,
            400,
        )

        other = self.add_member()
        other.team = self.team
        wrong_url = (
            f"/applications/{self.application.pk + 999}/team/members/"
            f"{other.pk}/remove/"
        )
        self.assertEqual(
            self.client.post(wrong_url, {}, format="json").status_code,
            404,
        )

    def test_captain_can_transfer_captainship(self):
        self.authenticate(self.captain)
        response = self.client.post(
            f"/applications/{self.application.pk}/team/transfer-captain/",
            {"member_id": self.member.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.team.refresh_from_db()
        self.assertEqual(self.application.user, self.member_user)
        self.assertEqual(self.team.captain, self.member_user)

    def test_transfer_rejects_manager_and_invalid_target(self):
        url = f"/applications/{self.application.pk}/team/transfer-captain/"
        self.authenticate(self.manager)
        self.assertEqual(
            self.client.post(
                url,
                {"member_id": self.member.pk},
                format="json",
            ).status_code,
            403,
        )

        self.member.status = TeamMember.STATUS_INVITED
        self.member.save(update_fields=["status", "updated_at"])
        self.authenticate(self.captain)
        self.assertEqual(
            self.client.post(
                url,
                {"member_id": self.member.pk},
                format="json",
            ).status_code,
            400,
        )

    def test_application_response_contains_compact_team_summary(self):
        self.authenticate(self.captain)
        response = self.client.get(f"/applications/{self.application.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data["team"]),
            {
                "id",
                "name",
                "captain_id",
                "accepted_members_count",
                "current_user_role",
            },
        )
        self.assertEqual(response.data["team"]["accepted_members_count"], 2)
        self.assertIn("form_data", response.data)
        self.assertIn("participation_mode", response.data)

    def test_member_and_manager_get_read_only_application_access(self):
        detail_url = f"/applications/{self.application.pk}/"
        for user in (self.member_user, self.manager):
            self.authenticate(user)
            with self.subTest(user=user):
                self.assertEqual(self.client.get(detail_url).status_code, 200)
                self.assertEqual(
                    self.client.patch(
                        detail_url,
                        {"form_data": {"changed": True}},
                        format="json",
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        f"/applications/{self.application.pk}/submit/",
                        {},
                        format="json",
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        f"/applications/{self.application.pk}/withdraw/",
                        {},
                        format="json",
                    ).status_code,
                    403,
                )

    def test_my_application_prefers_owned_then_accepted_team_membership(self):
        self.authenticate(self.member_user)
        url = f"/programs/{self.program.pk}/applications/my/"
        membership_response = self.client.get(url)
        self.assertEqual(membership_response.status_code, 200)
        self.assertEqual(membership_response.data["id"], self.application.pk)

        own = Application.objects.create(
            program=self.program,
            user=self.member_user,
            created_by=self.member_user,
        )
        own_response = self.client.get(url)
        self.assertEqual(own_response.data["id"], own.pk)

    def test_my_application_returns_latest_terminal_team_membership(self):
        Application.objects.filter(pk=self.application.pk).update(
            status=Application.STATUS_WITHDRAWN,
            withdrawn_at=timezone.now(),
        )
        self.authenticate(self.member_user)

        response = self.client.get(
            f"/programs/{self.program.pk}/applications/my/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], self.application.pk)

    def test_historical_member_does_not_get_application_access(self):
        self.member.status = TeamMember.STATUS_REMOVED
        self.member.save(update_fields=["status", "updated_at"])
        self.authenticate(self.member_user)

        self.assertEqual(
            self.client.get(f"/applications/{self.application.pk}/").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/programs/{self.program.pk}/applications/my/"
            ).status_code,
            404,
        )

    def test_member_and_manager_have_read_only_submission_access(self):
        Application.objects.filter(pk=self.application.pk).update(
            status=Application.STATUS_SUBMITTED,
            submitted_at=timezone.now(),
        )
        submission = Submission.objects.create(
            application=self.application,
            program=self.program,
            submitted_by=self.captain,
            title="Командное решение",
        )
        list_url = f"/applications/{self.application.pk}/submissions/"
        detail_url = f"/submissions/{submission.pk}/"

        for user in (self.member_user, self.manager):
            self.authenticate(user)
            with self.subTest(user=user):
                self.assertEqual(self.client.get(list_url).status_code, 200)
                self.assertEqual(self.client.get(detail_url).status_code, 200)
                self.assertEqual(
                    self.client.post(
                        list_url,
                        {"title": "Запрещено"},
                        format="json",
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.patch(
                        detail_url,
                        {"title": "Запрещено"},
                        format="json",
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        f"/submissions/{submission.pk}/submit/",
                        {},
                        format="json",
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        f"/submissions/{submission.pk}/cancel/",
                        {},
                        format="json",
                    ).status_code,
                    403,
                )

    def test_outsider_cannot_read_submission(self):
        submission = Submission.objects.create(
            application=self.application,
            program=self.program,
            submitted_by=self.captain,
            title="Закрытое решение",
        )
        self.authenticate(self.outsider)
        self.assertEqual(
            self.client.get(f"/submissions/{submission.pk}/").status_code,
            404,
        )

    def test_transfer_moves_submission_write_access_to_new_captain(self):
        submission = Submission.objects.create(
            application=self.application,
            program=self.program,
            submitted_by=self.captain,
            title="Черновик",
        )
        self.authenticate(self.captain)
        transfer_response = self.client.post(
            f"/applications/{self.application.pk}/team/transfer-captain/",
            {"member_id": self.member.pk},
            format="json",
        )
        self.assertEqual(transfer_response.status_code, 200)

        detail_url = f"/submissions/{submission.pk}/"
        old_captain_response = self.client.patch(
            detail_url,
            {"title": "Запрещено"},
            format="json",
        )
        self.assertEqual(old_captain_response.status_code, 403)
        self.assertEqual(self.client.get(detail_url).status_code, 200)

        self.authenticate(self.member_user)
        new_captain_response = self.client.patch(
            detail_url,
            {"title": "Новый капитан"},
            format="json",
        )
        self.assertEqual(new_captain_response.status_code, 200)
        self.assertEqual(new_captain_response.data["title"], "Новый капитан")
