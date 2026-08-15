from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from invites.models import Invite
from invites.tests.helpers import (
    add_collaborator,
    add_user_to_program,
    create_invite,
    create_project,
    create_user,
    link_project_to_program,
)
from projects.models import Collaborator
from notifications.models import Notification


class ProjectWorkspaceInvitationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.leader = create_user(prefix="workspace-invite-leader")
        self.collaborator = create_user(prefix="workspace-invite-collaborator")
        self.recipient = create_user(prefix="workspace-invite-recipient")
        self.outsider = create_user(prefix="workspace-invite-outsider")
        self.staff = create_user(prefix="workspace-invite-staff", is_staff=True)
        self.project = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )
        add_collaborator(project=self.project, user=self.collaborator)

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def invitations_url(self, project=None):
        project = project or self.project
        return f"/projects/{project.pk}/workspace/invitations/"

    def revoke_url(self, invitation, project=None):
        project = project or self.project
        return f"{self.invitations_url(project)}{invitation.pk}/revoke/"

    @staticmethod
    def incoming_url():
        return "/projects/workspace/invitations/incoming/"

    @staticmethod
    def accept_url(invitation):
        return f"/projects/workspace/invitations/{invitation.pk}/accept/"

    @staticmethod
    def decline_url(invitation):
        return f"/projects/workspace/invitations/{invitation.pk}/decline/"

    def create_workspace_invitation(self, *, recipient=None, **overrides):
        recipient = recipient or self.recipient
        defaults = {
            "project": self.project,
            "user": recipient,
            "invited_by": self.leader,
            "role": "Разработчик",
            "specialization": "Backend",
            "motivational_letter": "Присоединяйтесь к проекту",
        }
        defaults.update(overrides)
        return Invite.objects.create(**defaults)

    def test_workspace_invitation_endpoints_require_authentication(self):
        invitation = self.create_workspace_invitation()

        responses = (
            self.client.get(self.invitations_url()),
            self.client.post(
                self.invitations_url(),
                {"recipient_id": self.outsider.pk},
                format="json",
            ),
            self.client.get(self.incoming_url()),
            self.client.post(self.accept_url(invitation), {}, format="json"),
            self.client.post(self.decline_url(invitation), {}, format="json"),
            self.client.post(self.revoke_url(invitation), {}, format="json"),
        )

        self.assertTrue(
            all(
                response.status_code == status.HTTP_401_UNAUTHORIZED
                for response in responses
            )
        )

    def test_leader_creates_pending_invitation_with_safe_response(self):
        self.authenticate(self.leader)

        response = self.client.post(
            self.invitations_url(),
            {
                "recipient_id": self.recipient.pk,
                "role": "Разработчик",
                "specialization": "Backend",
                "message": "Присоединяйтесь к проекту",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        invitation = Invite.objects.get(pk=response.data["id"])
        self.assertEqual(invitation.project, self.project)
        self.assertEqual(invitation.user, self.recipient)
        self.assertEqual(invitation.invited_by, self.leader)
        self.assertEqual(invitation.status, Invite.STATUS_PENDING)
        self.assertEqual(response.data["status"], Invite.STATUS_PENDING)
        self.assertEqual(response.data["project"]["id"], self.project.pk)
        self.assertEqual(response.data["sender"]["id"], self.leader.pk)
        self.assertEqual(response.data["recipient"]["id"], self.recipient.pk)
        self.assertNotIn("email", response.data["recipient"])
        self.assertEqual(response.data["message"], "Присоединяйтесь к проекту")
        self.assertIsNone(response.data["processed_at"])
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.recipient,
                type=Notification.Type.PROJECT_INVITE_CREATED,
            ).exists()
        )

    def test_only_leader_or_staff_can_create_invitation(self):
        for actor, expected_status in (
            (self.collaborator, status.HTTP_403_FORBIDDEN),
            (self.outsider, status.HTTP_404_NOT_FOUND),
        ):
            with self.subTest(actor=actor.pk):
                self.authenticate(actor)
                response = self.client.post(
                    self.invitations_url(),
                    {"recipient_id": self.recipient.pk},
                    format="json",
                )
                self.assertEqual(response.status_code, expected_status)

        self.authenticate(self.staff)
        staff_response = self.client.post(
            self.invitations_url(),
            {"recipient_id": self.recipient.pk},
            format="json",
        )
        self.assertEqual(staff_response.status_code, status.HTTP_201_CREATED)

    def test_create_rejects_leader_collaborator_duplicate_and_invalid_user(self):
        self.authenticate(self.leader)
        invalid_targets = (
            (self.leader.pk, status.HTTP_400_BAD_REQUEST),
            (self.collaborator.pk, status.HTTP_400_BAD_REQUEST),
            (999999, status.HTTP_400_BAD_REQUEST),
        )
        for recipient_id, expected_status in invalid_targets:
            with self.subTest(recipient_id=recipient_id):
                response = self.client.post(
                    self.invitations_url(),
                    {"recipient_id": recipient_id},
                    format="json",
                )
                self.assertEqual(response.status_code, expected_status)
                self.assertIn("recipient_id", response.data)

        self.create_workspace_invitation()
        duplicate_response = self.client.post(
            self.invitations_url(),
            {"recipient_id": self.recipient.pk},
            format="json",
        )
        self.assertEqual(duplicate_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            Invite.objects.filter(project=self.project, user=self.recipient).count(),
            1,
        )

    def test_create_rejects_inactive_user_and_read_only_identifiers(self):
        inactive = create_user(prefix="workspace-invite-inactive")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        self.authenticate(self.leader)

        inactive_response = self.client.post(
            self.invitations_url(),
            {"recipient_id": inactive.pk},
            format="json",
        )
        self.assertEqual(inactive_response.status_code, status.HTTP_400_BAD_REQUEST)

        for forbidden_field in ("project", "user", "recipient", "sender", "status"):
            with self.subTest(field=forbidden_field):
                response = self.client.post(
                    self.invitations_url(),
                    {
                        "recipient_id": self.recipient.pk,
                        forbidden_field: self.outsider.pk,
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(forbidden_field, response.data)

        self.assertFalse(
            Invite.objects.filter(project=self.project, user=self.recipient).exists()
        )

    def test_legacy_program_project_requires_recipient_membership(self):
        program = link_project_to_program(project=self.project)
        self.authenticate(self.leader)

        rejected = self.client.post(
            self.invitations_url(),
            {"recipient_id": self.recipient.pk},
            format="json",
        )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)

        add_user_to_program(user=self.recipient, program=program)
        accepted = self.client.post(
            self.invitations_url(),
            {"recipient_id": self.recipient.pk},
            format="json",
        )
        self.assertEqual(accepted.status_code, status.HTTP_201_CREATED)

    def test_leader_lists_only_project_invitation_history(self):
        own_pending = self.create_workspace_invitation()
        own_declined = self.create_workspace_invitation(
            recipient=self.outsider,
            is_accepted=False,
        )
        other_project = create_project(leader=self.leader)
        create_invite(project=other_project)
        self.authenticate(self.leader)

        response = self.client.get(self.invitations_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {item["id"] for item in response.data},
            {own_pending.pk, own_declined.pk},
        )
        self.assertEqual(
            {item["project"]["id"] for item in response.data},
            {self.project.pk},
        )

    def test_collaborator_and_outsider_cannot_list_project_invitations(self):
        self.create_workspace_invitation()
        for actor, expected_status in (
            (self.collaborator, status.HTTP_403_FORBIDDEN),
            (self.outsider, status.HTTP_404_NOT_FOUND),
        ):
            with self.subTest(actor=actor.pk):
                self.authenticate(actor)
                response = self.client.get(self.invitations_url())
                self.assertEqual(response.status_code, expected_status)

    def test_recipient_lists_only_own_incoming_invitation_history(self):
        own = self.create_workspace_invitation()
        own_declined = self.create_workspace_invitation(
            project=create_project(),
            user=self.recipient,
            invited_by=None,
            is_accepted=False,
        )
        self.create_workspace_invitation(recipient=self.outsider)
        self.authenticate(self.recipient)

        response = self.client.get(self.incoming_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data], [own.pk, own_declined.pk]
        )
        self.assertTrue(
            all(item["recipient"]["id"] == self.recipient.pk for item in response.data)
        )

    def test_recipient_accepts_invitation_atomically_and_only_once(self):
        invitation = self.create_workspace_invitation()
        self.authenticate(self.recipient)

        response = self.client.post(self.accept_url(invitation), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        invitation.refresh_from_db()
        collaborator = Collaborator.objects.get(
            project=self.project,
            user=self.recipient,
        )
        self.assertEqual(invitation.status, Invite.STATUS_ACCEPTED)
        self.assertIsNotNone(invitation.resolved_at)
        self.assertEqual(collaborator.role, invitation.role)
        self.assertEqual(collaborator.specialization, invitation.specialization)
        self.assertEqual(response.data["status"], Invite.STATUS_ACCEPTED)
        self.assertIsNotNone(response.data["processed_at"])
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.leader,
                type=Notification.Type.PROJECT_INVITE_ACCEPTED,
            ).exists()
        )

        repeated = self.client.post(self.accept_url(invitation), {}, format="json")
        self.assertEqual(repeated.status_code, status.HTTP_409_CONFLICT)
        decline_after_accept = self.client.post(
            self.decline_url(invitation), {}, format="json"
        )
        self.assertEqual(decline_after_accept.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            Collaborator.objects.filter(
                project=self.project,
                user=self.recipient,
            ).count(),
            1,
        )

    def test_failed_accept_rolls_back_invitation_and_collaborator(self):
        invitation = self.create_workspace_invitation()
        self.authenticate(self.recipient)

        with patch(
            "invites.workspace_services.Collaborator.objects.create",
            side_effect=IntegrityError("forced failure"),
        ):
            with self.assertRaises(IntegrityError):
                self.client.post(self.accept_url(invitation), {}, format="json")

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invite.STATUS_PENDING)
        self.assertIsNone(invitation.resolved_at)
        self.assertFalse(
            Collaborator.objects.filter(
                project=self.project,
                user=self.recipient,
            ).exists()
        )

    def test_other_user_cannot_accept_or_decline_invitation(self):
        invitation = self.create_workspace_invitation()
        self.authenticate(self.outsider)

        self.assertEqual(
            self.client.post(self.accept_url(invitation), {}, format="json").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(self.decline_url(invitation), {}, format="json").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invite.STATUS_PENDING)

    def test_recipient_declines_once_and_declined_or_revoked_cannot_be_accepted(self):
        declined = self.create_workspace_invitation()
        revoked = self.create_workspace_invitation(recipient=self.outsider)

        self.authenticate(self.recipient)
        decline_response = self.client.post(self.decline_url(declined), {}, format="json")
        self.assertEqual(decline_response.status_code, status.HTTP_200_OK)
        self.assertEqual(decline_response.data["status"], Invite.STATUS_DECLINED)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.leader,
                type=Notification.Type.PROJECT_INVITE_DECLINED,
            ).exists()
        )
        repeated_decline = self.client.post(self.decline_url(declined), {}, format="json")
        self.assertEqual(repeated_decline.status_code, status.HTTP_409_CONFLICT)
        declined_accept = self.client.post(self.accept_url(declined), {}, format="json")
        self.assertEqual(declined_accept.status_code, status.HTTP_409_CONFLICT)

        self.authenticate(self.leader)
        revoke_response = self.client.post(self.revoke_url(revoked), {}, format="json")
        self.assertEqual(revoke_response.status_code, status.HTTP_200_OK)
        self.authenticate(self.outsider)
        revoked_accept = self.client.post(self.accept_url(revoked), {}, format="json")
        self.assertEqual(revoked_accept.status_code, status.HTTP_409_CONFLICT)

    def test_leader_revokes_pending_invitation_without_deleting_history(self):
        invitation = self.create_workspace_invitation()
        self.authenticate(self.leader)

        response = self.client.post(self.revoke_url(invitation), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invite.STATUS_REVOKED)
        self.assertIsNotNone(invitation.resolved_at)
        self.assertTrue(Invite.objects.filter(pk=invitation.pk).exists())
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.recipient,
                type=Notification.Type.PROJECT_INVITE_REVOKED,
            ).exists()
        )
        repeated = self.client.post(self.revoke_url(invitation), {}, format="json")
        self.assertEqual(repeated.status_code, status.HTTP_409_CONFLICT)

    def test_collaborator_outsider_and_wrong_project_cannot_revoke(self):
        invitation = self.create_workspace_invitation()
        other_project = create_project(leader=self.leader)

        self.authenticate(self.collaborator)
        self.assertEqual(
            self.client.post(self.revoke_url(invitation), {}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.authenticate(self.outsider)
        self.assertEqual(
            self.client.post(self.revoke_url(invitation), {}, format="json").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.authenticate(self.leader)
        self.assertEqual(
            self.client.post(
                self.revoke_url(invitation, other_project),
                {},
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_staff_can_revoke_but_processed_invitation_cannot_be_revoked(self):
        pending = self.create_workspace_invitation()
        processed = self.create_workspace_invitation(
            recipient=self.outsider,
            is_accepted=False,
        )
        self.authenticate(self.staff)

        self.assertEqual(
            self.client.post(self.revoke_url(pending), {}, format="json").status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post(self.revoke_url(processed), {}, format="json").status_code,
            status.HTTP_409_CONFLICT,
        )

    def test_action_payload_cannot_override_project_recipient_or_status(self):
        invitation = self.create_workspace_invitation()
        self.authenticate(self.recipient)

        response = self.client.post(
            self.accept_url(invitation),
            {"project": 999, "recipient_id": self.outsider.pk, "status": "accepted"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invite.STATUS_PENDING)
        self.assertFalse(
            Collaborator.objects.filter(
                project=self.project, user=self.recipient
            ).exists()
        )

    def test_database_rejects_two_active_invitations(self):
        self.create_workspace_invitation()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_workspace_invitation()

        self.assertEqual(
            Invite.objects.filter(project=self.project, user=self.recipient).count(),
            1,
        )

    def test_completed_invitation_allows_a_new_pending_invitation(self):
        self.create_workspace_invitation(is_accepted=False)

        invitation = self.create_workspace_invitation()

        self.assertEqual(invitation.status, Invite.STATUS_PENDING)
        self.assertEqual(
            Invite.objects.filter(project=self.project, user=self.recipient).count(),
            2,
        )

    def test_project_and_incoming_lists_have_bounded_queries(self):
        self.create_workspace_invitation()
        for index in range(5):
            recipient = create_user(prefix=f"workspace-list-recipient-{index}")
            self.create_workspace_invitation(recipient=recipient)
        self.authenticate(self.leader)

        with CaptureQueriesContext(connection) as project_queries:
            project_response = self.client.get(self.invitations_url())
        self.authenticate(self.recipient)
        with CaptureQueriesContext(connection) as incoming_queries:
            incoming_response = self.client.get(self.incoming_url())

        self.assertEqual(project_response.status_code, status.HTTP_200_OK)
        self.assertEqual(incoming_response.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(project_queries), 4)
        self.assertLessEqual(len(incoming_queries), 2)

    def test_legacy_invite_and_workspace_content_endpoints_remain_available(self):
        self.authenticate(self.leader)

        legacy_response = self.client.post(
            "/invites/",
            {
                "project": self.project.pk,
                "user": self.recipient.pk,
                "role": "Legacy role",
            },
            format="json",
        )
        workspace_response = self.client.get(f"/projects/{self.project.pk}/workspace/")
        goals_response = self.client.get(f"/projects/{self.project.pk}/workspace/goals/")
        achievements_response = self.client.get(
            f"/projects/{self.project.pk}/workspace/achievements/"
        )

        self.assertEqual(legacy_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(workspace_response.status_code, status.HTTP_200_OK)
        self.assertEqual(goals_response.status_code, status.HTTP_200_OK)
        self.assertEqual(achievements_response.status_code, status.HTTP_200_OK)
