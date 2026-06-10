from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from projects.models import Collaborator
from invites.tests.helpers import create_invite, create_user


class InviteDecisionAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_invited_user_can_accept_invite_and_become_collaborator(self):
        recipient = create_user(prefix="recipient")
        invite = create_invite(
            user=recipient,
            role="Analyst",
            specialization="Market research",
        )
        self.client.force_authenticate(recipient)

        response = self.client.post(f"/invites/{invite.id}/accept/")

        invite.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(invite.is_accepted)
        self.assertTrue(
            Collaborator.objects.filter(
                project=invite.project,
                user=recipient,
                role="Analyst",
                specialization="Market research",
            ).exists()
        )

    def test_invited_user_can_decline_invite(self):
        recipient = create_user(prefix="recipient")
        invite = create_invite(user=recipient)
        self.client.force_authenticate(recipient)

        response = self.client.post(f"/invites/{invite.id}/decline/")

        invite.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(invite.is_accepted)

    def test_other_user_cannot_accept_or_decline_invite(self):
        invite = create_invite()
        outsider = create_user(prefix="outsider")
        self.client.force_authenticate(outsider)

        accept_response = self.client.post(f"/invites/{invite.id}/accept/")
        decline_response = self.client.post(f"/invites/{invite.id}/decline/")

        invite.refresh_from_db()
        self.assertEqual(accept_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(decline_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIsNone(invite.is_accepted)

    def test_project_leader_cannot_accept_or_decline_invite(self):
        invite = create_invite()
        self.client.force_authenticate(invite.project.leader)

        accept_response = self.client.post(f"/invites/{invite.id}/accept/")
        decline_response = self.client.post(f"/invites/{invite.id}/decline/")

        invite.refresh_from_db()
        self.assertEqual(accept_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(decline_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIsNone(invite.is_accepted)

    def test_accepting_already_accepted_invite_returns_conflict(self):
        recipient = create_user(prefix="recipient")
        invite = create_invite(user=recipient, is_accepted=True)
        self.client.force_authenticate(recipient)

        response = self.client.post(f"/invites/{invite.id}/accept/")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_accepting_declined_invite_returns_conflict(self):
        recipient = create_user(prefix="recipient")
        invite = create_invite(user=recipient, is_accepted=False)
        self.client.force_authenticate(recipient)

        response = self.client.post(f"/invites/{invite.id}/accept/")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_declining_already_accepted_invite_returns_conflict(self):
        recipient = create_user(prefix="recipient")
        invite = create_invite(user=recipient, is_accepted=True)
        self.client.force_authenticate(recipient)

        response = self.client.post(f"/invites/{invite.id}/decline/")

        invite.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(invite.is_accepted)

    def test_declining_already_declined_invite_returns_conflict(self):
        recipient = create_user(prefix="recipient")
        invite = create_invite(user=recipient, is_accepted=False)
        self.client.force_authenticate(recipient)

        response = self.client.post(f"/invites/{invite.id}/decline/")

        invite.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(invite.is_accepted)

    def test_decline_after_accept_returns_conflict_and_keeps_collaborator(self):
        recipient = create_user(prefix="recipient")
        invite = create_invite(user=recipient)
        self.client.force_authenticate(recipient)

        accept_response = self.client.post(f"/invites/{invite.id}/accept/")
        decline_response = self.client.post(f"/invites/{invite.id}/decline/")

        invite.refresh_from_db()
        self.assertEqual(accept_response.status_code, status.HTTP_200_OK)
        self.assertEqual(decline_response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(invite.is_accepted)
        self.assertTrue(
            Collaborator.objects.filter(project=invite.project, user=recipient).exists()
        )
