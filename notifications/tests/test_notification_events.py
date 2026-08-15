from django.test import TestCase

from news.tests.helpers import create_partner_program, create_user
from notifications.events import notify_submission_status_changed
from notifications.models import Notification
from partner_programs.models import Application, Submission, Team, TeamMember


class NotificationEventTests(TestCase):
    def test_submission_status_notifies_owner_and_only_accepted_team_members(self):
        owner = create_user(prefix="notification-owner")
        accepted = create_user(prefix="notification-accepted")
        invited = create_user(prefix="notification-invited")
        removed = create_user(prefix="notification-removed")
        actor = create_user(prefix="notification-manager")
        program = create_partner_program(manager=actor)
        application = Application.objects.create(
            program=program,
            user=owner,
            created_by=owner,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
            status=Application.STATUS_SUBMITTED,
        )
        team = Team.objects.create(
            application=application,
            name="Команда",
            captain=owner,
        )
        for user, role, status in (
            (owner, TeamMember.ROLE_CAPTAIN, TeamMember.STATUS_ACCEPTED),
            (accepted, TeamMember.ROLE_MEMBER, TeamMember.STATUS_ACCEPTED),
            (invited, TeamMember.ROLE_MEMBER, TeamMember.STATUS_INVITED),
            (removed, TeamMember.ROLE_MEMBER, TeamMember.STATUS_REMOVED),
        ):
            TeamMember.objects.create(
                team=team,
                user=user,
                role=role,
                status=status,
                invited_by=owner,
            )
        submission = Submission.objects.create(
            application=application,
            program=program,
            submitted_by=owner,
            title="Решение",
            status=Submission.STATUS_RETURNED,
        )

        notify_submission_status_changed(submission, actor=actor)

        notifications = Notification.objects.filter(
            type=Notification.Type.SUBMISSION_STATUS_CHANGED
        )
        self.assertEqual(
            set(notifications.values_list("recipient_id", flat=True)),
            {owner.pk, accepted.pk},
        )
        self.assertFalse(notifications.filter(recipient__in=[invited, removed]).exists())
        self.assertTrue(
            all(
                item.action_url == f"/office/program/{program.pk}/submission"
                for item in notifications
            )
        )
