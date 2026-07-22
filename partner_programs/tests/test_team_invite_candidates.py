from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    Application,
    PartnerProgram,
    Team,
    TeamInvite,
    TeamMember,
)
from partner_programs.services.application_team import (
    ApplicationDeadlinePassedError,
    ApplicationNotEditableError,
    create_or_get_application,
)
from partner_programs.services.team_invites import (
    TeamInviteActiveApplicationConflictError,
    TeamInviteCapacityReachedError,
    TeamInvitePermissionError,
    TeamInviteTargetInvalidError,
    create_team_invite,
    get_team_invite_candidates,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)
from partner_programs.throttling import (
    TeamInviteCandidateSearchScopedRateThrottle,
)


class TeamInviteCandidateFixtureMixin:
    def setUp(self):
        cache.clear()
        self.captain = create_user(
            prefix="candidate-captain",
            first_name="Капитан",
            last_name="Команды",
        )
        self.accepted_user = create_user(
            prefix="candidate-member",
            first_name="Принятый",
            last_name="Участник",
        )
        self.manager = create_user(prefix="candidate-manager")
        self.staff = create_user(prefix="candidate-staff", is_staff=True)
        self.outsider = create_user(prefix="candidate-outsider")
        self.program = create_partner_program(
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
            team_min_size=2,
            team_max_size=50,
        )
        self.program.managers.add(self.manager)
        create_program_member(self.program, user=self.captain)
        create_program_member(self.program, user=self.accepted_user)
        self.application = create_or_get_application(
            program=self.program,
            user=self.captain,
            created_by=self.captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            team_name="Поиск кандидатов",
        ).application
        self.team = self.application.team
        self.accepted_member = TeamMember.objects.create(
            team=self.team,
            user=self.accepted_user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
            invited_by=self.captain,
        )

    def create_candidate(
        self,
        *,
        first_name="Иван",
        last_name="Кандидатов",
        register=True,
        is_active=True,
        prefix="candidate-user",
    ):
        user = create_user(
            prefix=prefix,
            first_name=first_name,
            last_name=last_name,
            is_active=is_active,
        )
        if register:
            create_program_member(self.program, user=user, data={"secret": "hidden"})
        return user

    def candidate_ids(self, query="кандидат"):
        return list(
            get_team_invite_candidates(
                team=self.team,
                actor=self.captain,
                query=query,
            ).values_list("pk", flat=True)
        )

    def reload_team(self):
        self.team = Team.objects.select_related(
            "application",
            "application__program",
            "captain",
        ).get(pk=self.team.pk)


class TeamInviteCandidateSelectorTests(TeamInviteCandidateFixtureMixin, TestCase):
    def test_searches_by_first_name_last_name_and_both_orders(self):
        user = self.create_candidate(first_name="Иван", last_name="Петров")

        for query in ("иван", "петров", "иван петров", "петров иван"):
            with self.subTest(query=query):
                self.assertEqual(self.candidate_ids(query), [user.pk])

    def test_search_is_case_insensitive_and_supports_email_prefix(self):
        user = self.create_candidate(first_name="Анна", last_name="Смирнова")

        self.assertEqual(self.candidate_ids("АННА"), [user.pk])
        self.assertEqual(
            self.candidate_ids(user.email.split("@", maxsplit=1)[0]),
            [user.pk],
        )

    def test_results_have_stable_case_insensitive_sorting(self):
        first = self.create_candidate(first_name="Борис", last_name="Тест Альфа")
        second = self.create_candidate(first_name="Анна", last_name="тест альфа")
        third = self.create_candidate(first_name="Анна", last_name="Тест Бета")

        first_result = self.candidate_ids("тест")
        second_result = self.candidate_ids("ТЕСТ")

        self.assertEqual(first_result, second_result)
        self.assertEqual(set(first_result), {first.pk, second.pk, third.pk})

    def test_related_history_does_not_duplicate_candidate(self):
        user = self.create_candidate()
        TeamInvite.objects.create(
            team=self.team,
            user=user,
            invited_by=self.captain,
            status=TeamInvite.STATUS_DECLINED,
            resolved_at=timezone.now(),
        )
        TeamInvite.objects.create(
            team=self.team,
            user=user,
            invited_by=self.captain,
            status=TeamInvite.STATUS_REVOKED,
            resolved_at=timezone.now(),
        )
        TeamMember.objects.create(
            team=self.team,
            user=user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_LEFT,
            invited_by=self.captain,
        )

        self.assertEqual(self.candidate_ids(), [user.pk])

    def test_result_count_is_limited_to_twenty(self):
        for index in range(25):
            self.create_candidate(
                first_name=f"Кандидат {str(index).zfill(2)}",
                last_name="Лимитов",
                prefix="candidate-limit",
            )

        self.assertEqual(len(self.candidate_ids("лимитов")), 20)

    def test_registered_free_user_is_returned(self):
        user = self.create_candidate()

        self.assertEqual(self.candidate_ids(), [user.pk])

    def test_unregistered_and_inactive_users_are_excluded(self):
        unregistered = self.create_candidate(register=False)
        inactive = self.create_candidate(is_active=False)

        result = self.candidate_ids()

        self.assertNotIn(unregistered.pk, result)
        self.assertNotIn(inactive.pk, result)

    def test_captain_and_accepted_member_are_excluded(self):
        self.assertNotIn(self.captain.pk, self.candidate_ids("капитан"))
        self.assertNotIn(self.accepted_user.pk, self.candidate_ids("принятый"))

    def test_pending_invite_in_current_team_is_excluded(self):
        user = self.create_candidate()
        create_team_invite(
            team=self.team,
            actor=self.captain,
            target=user,
        )

        self.assertNotIn(user.pk, self.candidate_ids())

    def test_active_owned_application_is_excluded(self):
        user = self.create_candidate()
        Application.objects.create(
            program=self.program,
            user=user,
            created_by=user,
        )

        self.assertNotIn(user.pk, self.candidate_ids())

    def test_accepted_membership_in_other_active_team_is_excluded(self):
        user = self.create_candidate()
        other_captain = self.create_candidate(
            first_name="Другой",
            last_name="Капитан",
            prefix="candidate-other-captain",
        )
        other_application = create_or_get_application(
            program=self.program,
            user=other_captain,
            created_by=other_captain,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            team_name="Другая команда",
        ).application
        TeamMember.objects.create(
            team=other_application.team,
            user=user,
            role=TeamMember.ROLE_MEMBER,
            status=TeamMember.STATUS_ACCEPTED,
            invited_by=other_captain,
        )

        self.assertNotIn(user.pk, self.candidate_ids())

    def test_resolved_invites_do_not_exclude_candidate(self):
        declined = self.create_candidate(prefix="candidate-declined")
        revoked = self.create_candidate(prefix="candidate-revoked")
        for user, invite_status in (
            (declined, TeamInvite.STATUS_DECLINED),
            (revoked, TeamInvite.STATUS_REVOKED),
        ):
            TeamInvite.objects.create(
                team=self.team,
                user=user,
                invited_by=self.captain,
                status=invite_status,
                resolved_at=timezone.now(),
            )

        result = self.candidate_ids()

        self.assertIn(declined.pk, result)
        self.assertIn(revoked.pk, result)

    def test_removed_and_left_members_can_be_candidates_again(self):
        removed = self.create_candidate(prefix="candidate-removed")
        left = self.create_candidate(prefix="candidate-left")
        for user, member_status in (
            (removed, TeamMember.STATUS_REMOVED),
            (left, TeamMember.STATUS_LEFT),
        ):
            TeamMember.objects.create(
                team=self.team,
                user=user,
                role=TeamMember.ROLE_MEMBER,
                status=member_status,
                invited_by=self.captain,
            )

        result = self.candidate_ids()

        self.assertIn(removed.pk, result)
        self.assertIn(left.pk, result)

    def test_terminal_application_does_not_exclude_candidate(self):
        user = self.create_candidate()
        Application.objects.create(
            program=self.program,
            user=user,
            created_by=user,
            status=Application.STATUS_WITHDRAWN,
        )

        self.assertIn(user.pk, self.candidate_ids())

    def test_selector_enforces_permission_and_team_state(self):
        self.create_candidate()
        with self.assertRaises(TeamInvitePermissionError):
            get_team_invite_candidates(
                team=self.team,
                actor=self.outsider,
                query="кандидат",
            )

        Application.objects.filter(pk=self.application.pk).update(
            participation_mode=Application.PARTICIPATION_MODE_INDIVIDUAL
        )
        self.reload_team()
        with self.assertRaises(TeamInviteTargetInvalidError):
            self.candidate_ids()

    def test_non_draft_deadline_and_capacity_are_rejected(self):
        self.application.status = Application.STATUS_SUBMITTED
        self.application.save(update_fields=["status", "updated_at"])
        self.reload_team()
        with self.assertRaises(ApplicationNotEditableError):
            self.candidate_ids()

        self.application.status = Application.STATUS_DRAFT
        self.application.save(update_fields=["status", "updated_at"])
        self.program.datetime_application_ends = (
            timezone.now() - timezone.timedelta(seconds=1)
        )
        self.program.save(update_fields=["datetime_application_ends"])
        self.reload_team()
        with self.assertRaises(ApplicationDeadlinePassedError):
            self.candidate_ids()

        self.program.datetime_application_ends = None
        self.program.team_max_size = 2
        self.program.save(
            update_fields=["datetime_application_ends", "team_max_size"]
        )
        self.reload_team()
        with self.assertRaises(TeamInviteCapacityReachedError):
            self.candidate_ids()

    def test_search_does_not_bypass_create_service_rechecks(self):
        user = self.create_candidate()
        self.assertIn(user.pk, self.candidate_ids())
        Application.objects.create(
            program=self.program,
            user=user,
            created_by=user,
        )

        with self.assertRaises(TeamInviteActiveApplicationConflictError):
            create_team_invite(
                team=self.team,
                actor=self.captain,
                target=user,
            )


class TeamInviteCandidateAPITests(TeamInviteCandidateFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    @property
    def url(self):
        return f"/applications/{self.application.pk}/team/invite-candidates/"

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_captain_and_staff_can_search(self):
        user = self.create_candidate()
        for actor in (self.captain, self.staff):
            self.authenticate(actor)
            with self.subTest(actor=actor):
                response = self.client.get(self.url, {"q": "кандидат"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual([item["id"] for item in response.data], [user.pk])

    def test_member_and_manager_get_403_outsider_gets_404(self):
        for actor in (self.accepted_user, self.manager):
            self.authenticate(actor)
            with self.subTest(actor=actor):
                self.assertEqual(
                    self.client.get(self.url, {"q": "кандидат"}).status_code,
                    403,
                )

        self.authenticate(self.outsider)
        self.assertEqual(
            self.client.get(self.url, {"q": "кандидат"}).status_code,
            404,
        )

        invited_user = self.create_candidate(prefix="candidate-invited-user")
        create_team_invite(
            team=self.team,
            actor=self.captain,
            target=invited_user,
        )
        self.authenticate(invited_user)
        self.assertEqual(
            self.client.get(self.url, {"q": "кандидат"}).status_code,
            404,
        )

    def test_anonymous_gets_401(self):
        self.assertEqual(
            self.client.get(self.url, {"q": "кандидат"}).status_code,
            401,
        )

    def test_query_is_required_trimmed_and_limited(self):
        self.authenticate(self.captain)
        for params in ({}, {"q": ""}, {"q": "  аб  "}, {"q": "x" * 101}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)

        user = self.create_candidate(first_name="Иван", last_name="Иванов")
        response = self.client.get(self.url, {"q": "  ИВАНОВ  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data], [user.pk])

    def test_response_contains_only_safe_profile_fields(self):
        user = self.create_candidate()
        self.authenticate(self.captain)

        response = self.client.get(self.url, {"q": "кандидат"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["id"], user.pk)
        self.assertEqual(
            set(response.data[0]),
            {"id", "display_name", "avatar"},
        )
        for forbidden in (
            "email",
            "phone_number",
            "birthday",
            "partner_program_data",
            "application",
            "team",
        ):
            self.assertNotIn(forbidden, response.data[0])

    def test_non_draft_deadline_and_capacity_return_400(self):
        self.authenticate(self.captain)
        self.application.status = Application.STATUS_SUBMITTED
        self.application.save(update_fields=["status", "updated_at"])
        self.assertEqual(
            self.client.get(self.url, {"q": "кандидат"}).status_code,
            400,
        )

        self.application.status = Application.STATUS_DRAFT
        self.application.save(update_fields=["status", "updated_at"])
        self.program.datetime_application_ends = (
            timezone.now() - timezone.timedelta(seconds=1)
        )
        self.program.save(update_fields=["datetime_application_ends"])
        self.assertEqual(
            self.client.get(self.url, {"q": "кандидат"}).status_code,
            400,
        )

        self.program.datetime_application_ends = None
        self.program.team_max_size = 3
        self.program.save(
            update_fields=["datetime_application_ends", "team_max_size"]
        )
        pending_target = self.create_candidate(prefix="candidate-capacity-pending")
        create_team_invite(
            team=self.team,
            actor=self.captain,
            target=pending_target,
        )
        self.assertEqual(
            self.client.get(self.url, {"q": "кандидат"}).status_code,
            400,
        )

    def test_individual_application_without_team_returns_404(self):
        owner = create_user(prefix="candidate-individual-owner")
        create_program_member(self.program, user=owner)
        individual = Application.objects.create(
            program=self.program,
            user=owner,
            created_by=owner,
        )
        self.authenticate(owner)

        response = self.client.get(
            f"/applications/{individual.pk}/team/invite-candidates/",
            {"q": "кандидат"},
        )

        self.assertEqual(response.status_code, 404)

    @patch.object(
        TeamInviteCandidateSearchScopedRateThrottle,
        "rate",
        "1/min",
    )
    def test_search_has_dedicated_throttle(self):
        self.authenticate(self.captain)

        first = self.client.get(self.url, {"q": "кандидат"})
        second = self.client.get(self.url, {"q": "кандидат"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
