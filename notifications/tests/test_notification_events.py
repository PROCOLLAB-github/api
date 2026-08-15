from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from news.tests.helpers import create_partner_program, create_user
from notifications.events import (
    notify_application_status_changed,
    notify_application_submitted,
    notify_submission_status_changed,
    notify_submission_submitted,
)
from notifications.models import Notification
from partner_programs.models import Application, Submission, Team, TeamMember


class NotificationEventTests(TestCase):
    def test_application_transition_key_distinguishes_repeated_status_cycles(self):
        owner = create_user(prefix="application-transition-owner")
        manager = create_user(prefix="application-transition-manager")
        program = create_partner_program(manager=manager)
        first_submitted_at = timezone.now()
        application = Application.objects.create(
            program=program,
            user=owner,
            created_by=owner,
            status=Application.STATUS_SUBMITTED,
            submitted_at=first_submitted_at,
        )

        notify_application_submitted(application, actor=owner)
        notify_application_submitted(application, actor=owner)
        application.submitted_at = first_submitted_at + timedelta(seconds=1)
        application.save(update_fields=["submitted_at", "updated_at"])
        notify_application_submitted(application, actor=owner)

        application.status = Application.STATUS_WITHDRAWN
        application.save(update_fields=["status", "updated_at"])
        notify_application_status_changed(application, actor=manager)
        notify_application_status_changed(application, actor=manager)
        application.status = Application.STATUS_DRAFT
        application.save(update_fields=["status", "updated_at"])
        application.status = Application.STATUS_WITHDRAWN
        application.save(update_fields=["status", "updated_at"])
        notify_application_status_changed(application, actor=manager)

        self.assertEqual(
            Notification.objects.filter(
                type=Notification.Type.APPLICATION_SUBMITTED
            ).count(),
            2,
        )
        self.assertEqual(
            Notification.objects.filter(
                type=Notification.Type.APPLICATION_STATUS_CHANGED
            ).count(),
            2,
        )

    def test_submission_transition_key_distinguishes_repeated_status_cycles(self):
        owner = create_user(prefix="submission-transition-owner")
        manager = create_user(prefix="submission-transition-manager")
        program = create_partner_program(manager=manager)
        application = Application.objects.create(
            program=program,
            user=owner,
            created_by=owner,
            status=Application.STATUS_SUBMITTED,
        )
        first_submitted_at = timezone.now()
        submission = Submission.objects.create(
            application=application,
            program=program,
            submitted_by=owner,
            title="Решение",
            status=Submission.STATUS_SUBMITTED,
            submitted_at=first_submitted_at,
        )

        notify_submission_submitted(submission, actor=owner)
        notify_submission_submitted(submission, actor=owner)
        submission.submitted_at = first_submitted_at + timedelta(seconds=1)
        submission.save(update_fields=["submitted_at", "updated_at"])
        notify_submission_submitted(submission, actor=owner)

        submission.status = Submission.STATUS_RETURNED
        submission.save(update_fields=["status", "updated_at"])
        notify_submission_status_changed(submission, actor=manager)
        notify_submission_status_changed(submission, actor=manager)
        submission.status = Submission.STATUS_SUBMITTED
        submission.save(update_fields=["status", "updated_at"])
        submission.status = Submission.STATUS_RETURNED
        submission.save(update_fields=["status", "updated_at"])
        notify_submission_status_changed(submission, actor=manager)

        self.assertEqual(
            Notification.objects.filter(
                type=Notification.Type.SUBMISSION_SUBMITTED
            ).count(),
            2,
        )
        self.assertEqual(
            Notification.objects.filter(
                type=Notification.Type.SUBMISSION_STATUS_CHANGED
            ).count(),
            2,
        )

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
