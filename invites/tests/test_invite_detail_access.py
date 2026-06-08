from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from invites.models import Invite
from invites.tests.helpers import create_invite, create_user


class InviteDetailAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_anonymous_user_cannot_read_invite_detail(self):
        invite = create_invite()

        response = self.client.get(f"/invites/{invite.id}/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invited_user_can_read_invite_detail(self):
        recipient = create_user(prefix="recipient")
        invite = create_invite(user=recipient)
        self.client.force_authenticate(recipient)

        response = self.client.get(f"/invites/{invite.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], invite.id)

    def test_project_leader_can_read_invite_detail(self):
        invite = create_invite()
        self.client.force_authenticate(invite.project.leader)

        response = self.client.get(f"/invites/{invite.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], invite.id)

    def test_staff_can_read_invite_detail(self):
        staff = create_user(prefix="staff", is_staff=True)
        invite = create_invite()
        self.client.force_authenticate(staff)

        response = self.client.get(f"/invites/{invite.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], invite.id)

    def test_outsider_cannot_read_invite_detail(self):
        invite = create_invite()
        outsider = create_user(prefix="outsider")
        self.client.force_authenticate(outsider)

        response = self.client.get(f"/invites/{invite.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_project_leader_can_update_invite(self):
        invite = create_invite(motivational_letter="Initial")
        self.client.force_authenticate(invite.project.leader)

        response = self.client.patch(
            f"/invites/{invite.id}/",
            {"motivational_letter": "Changed by leader"},
            format="json",
        )

        invite.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(invite.motivational_letter, "Changed by leader")

    def test_invited_user_cannot_update_invite(self):
        invite = create_invite(motivational_letter="Initial")
        self.client.force_authenticate(invite.user)

        response = self.client.patch(
            f"/invites/{invite.id}/",
            {"motivational_letter": "Changed by recipient"},
            format="json",
        )

        invite.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(invite.motivational_letter, "Initial")

    def test_staff_cannot_update_invite(self):
        staff = create_user(prefix="staff", is_staff=True)
        invite = create_invite(motivational_letter="Initial")
        self.client.force_authenticate(staff)

        response = self.client.patch(
            f"/invites/{invite.id}/",
            {"motivational_letter": "Changed by staff"},
            format="json",
        )

        invite.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(invite.motivational_letter, "Initial")

    def test_outsider_cannot_update_invite(self):
        invite = create_invite(motivational_letter="Initial")
        outsider = create_user(prefix="outsider")
        self.client.force_authenticate(outsider)

        response = self.client.patch(
            f"/invites/{invite.id}/",
            {"motivational_letter": "Changed by outsider"},
            format="json",
        )

        invite.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(invite.motivational_letter, "Initial")

    def test_project_leader_can_delete_invite(self):
        invite = create_invite()
        self.client.force_authenticate(invite.project.leader)

        response = self.client.delete(f"/invites/{invite.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Invite.objects.filter(pk=invite.pk).exists())

    def test_invited_user_cannot_delete_invite(self):
        invite = create_invite()
        self.client.force_authenticate(invite.user)

        response = self.client.delete(f"/invites/{invite.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Invite.objects.filter(pk=invite.pk).exists())

    def test_outsider_cannot_delete_invite(self):
        invite = create_invite()
        outsider = create_user(prefix="outsider")
        self.client.force_authenticate(outsider)

        response = self.client.delete(f"/invites/{invite.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Invite.objects.filter(pk=invite.pk).exists())
