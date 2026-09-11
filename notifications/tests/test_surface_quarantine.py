from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from notifications.events import (
    notify_application_status_changed,
    notify_application_submitted,
    notify_evaluation_submitted,
    notify_expert_assignment_created,
    notify_expert_assignment_revoked,
    notify_news_comment_created,
    notify_project_invite_created,
    notify_project_invite_resolved,
    notify_submission_status_changed,
    notify_submission_submitted,
    notify_team_invite_created,
    notify_team_invite_resolved,
    notify_vacancy_response_created,
    notify_vacancy_response_resolved,
)


@override_settings(NEXTGEN_SURFACE_ENABLED=False)
class NotificationSurfaceQuarantineTests(SimpleTestCase):
    @patch("notifications.events.create_notifications")
    @patch("notifications.events.create_notification")
    def test_nextgen_events_do_not_write_notifications(
        self,
        create_notification,
        create_notifications,
    ):
        opaque_event = object()
        opaque_actor = object()

        notify_team_invite_created(opaque_event)
        notify_team_invite_resolved(opaque_event, actor=opaque_actor, status="accepted")
        notify_application_submitted(opaque_event, actor=opaque_actor)
        notify_application_status_changed(opaque_event, actor=opaque_actor)
        notify_submission_submitted(opaque_event, actor=opaque_actor)
        notify_submission_status_changed(opaque_event, actor=opaque_actor)
        notify_expert_assignment_created(opaque_event)
        notify_expert_assignment_revoked(opaque_event, actor=opaque_actor)
        notify_evaluation_submitted(opaque_event, actor=opaque_actor)
        notify_news_comment_created(opaque_event)

        create_notification.assert_not_called()
        create_notifications.assert_not_called()

    @patch("notifications.events.create_notification")
    def test_project_invite_events_remain_enabled(self, create_notification):
        leader = SimpleNamespace(pk=10, get_full_name=lambda: "Иван Иванов")
        project = SimpleNamespace(pk=20, leader_id=leader.pk, name="Альфа")
        invite = SimpleNamespace(
            pk=30,
            user_id=40,
            invited_by_id=leader.pk,
            project_id=project.pk,
            project=project,
        )

        notify_project_invite_created(invite)
        notify_project_invite_resolved(invite, actor=leader, status="revoked")

        self.assertEqual(create_notification.call_count, 2)
        self.assertEqual(
            create_notification.call_args_list[0].kwargs["action_url"],
            "/office/projects/invites",
        )
        self.assertEqual(
            create_notification.call_args_list[1].kwargs["action_url"],
            "/office/projects/invites",
        )

    @patch("notifications.events.create_notification")
    def test_vacancy_events_remain_enabled_with_angular_routes(
        self,
        create_notification,
    ):
        leader = SimpleNamespace(pk=10)
        applicant = SimpleNamespace(pk=40)
        vacancy = SimpleNamespace(
            pk=50,
            project_id=20,
            project=SimpleNamespace(leader_id=leader.pk),
            role="Дизайнер",
        )
        response = SimpleNamespace(pk=60, user_id=applicant.pk, vacancy=vacancy)

        notify_vacancy_response_created(response)
        notify_vacancy_response_resolved(response, actor=leader, accepted=True)

        self.assertEqual(create_notification.call_count, 2)
        self.assertEqual(
            create_notification.call_args_list[0].kwargs["action_url"],
            f"/office/vacancies/{vacancy.pk}",
        )
        self.assertEqual(
            create_notification.call_args_list[1].kwargs["action_url"],
            "/office/vacancies/my",
        )
