from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from projects.models import Project
from tests.constants import USER_CREATE_DATA

from users.views import UserList
from users.models import CustomUser
from invites.views import InviteList, InviteDetail, InviteAccept, InviteDecline
from invites.models import Invite
from industries.models import Industry
from projects.views import ProjectList, ProjectDetail


class InvitesTestCase(TestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()

        self.user_list_view = UserList.as_view()

        self.invite_list_view = InviteList.as_view()
        self.invite_detail_view = InviteDetail.as_view()

        self.project_list_view = ProjectList.as_view()
        self.project_detail_view = ProjectDetail.as_view()

        self.invite_create_data = {
            "project": "Test",
            "user": None,
            "motivational_letter": "hello",
            "role": "Developer",
            "is_accepted": False,
        }

        self.project_create_data = {
            "name": "Test",
            "description": "Test",
            "industry": Industry.objects.create(name="Test").id,
            "step": 1,
            "draft": False,
        }

    def test_invites_creation(self):
        user_main = self._user_create("example@gmail.com")
        user2 = self._user_create("example2@gmail.com")
        project = self._project_create(user_main)

        create_user = self.invite_create_data.copy()
        create_user["user"] = user2.id
        create_user["project"] = project.id
        request = self.factory.post("invites/", create_user, format="json")
        force_authenticate(request, user=user_main)

        response = self.invite_list_view(request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data["motivational_letter"],
            create_user["motivational_letter"],
        )
        self.assertEqual(response.data["project"]["id"], create_user["project"])
        self.assertEqual(response.data["role"], create_user["role"])
        self.assertEqual(response.data["is_accepted"], create_user["is_accepted"])

    def test_invites_creation_with_empty_text(self):
        user_main = self._user_create("example@gmail.com")
        user2 = self._user_create("example2@gmail.com")
        project = self._project_create(user_main)

        empty_text = self.invite_create_data.copy()
        empty_text["user"] = user2.id
        empty_text["project"] = project.id
        empty_text["motivational_letter"] = None
        request = self.factory.post("invites/", empty_text, format="json")
        force_authenticate(request, user=user_main)

        response = self.invite_list_view(request)

        self.assertEqual(response.status_code, 201)

    def test_invites_update(self):
        user_main = self._user_create("example@gmail.com")
        user2 = self._user_create("example2@gmail.com")
        project = self._project_create(user_main)

        updater = self.invite_create_data.copy()
        updater["user"] = user2.id
        updater["project"] = project.id
        request = self.factory.post("invites/", updater, format="json")
        force_authenticate(request, user=user_main)

        response = self.invite_list_view(request)

        invite_id = response.data["id"]
        invite = Invite.objects.get(id=invite_id)

        request = self.factory.patch(
            f"invites/{invite.pk}/", {"motivational_letter": "HELLO GUYS!"}
        )
        force_authenticate(request, user=user_main)
        response = self.invite_detail_view(request, pk=invite.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["motivational_letter"], "HELLO GUYS!")

    def test_invites_creation_with_empty_data(self):
        user_main = self._user_create("example@gmail.com")

        empty_data = {}

        request = self.factory.post("invites/", empty_data, format="json")
        force_authenticate(request, user=user_main)
        response = self.invite_list_view(request)

        self.assertEqual(response.status_code, 400)

    def test_accept_invite_by_intended_user(self):
        sender = self._user_create("sender@example.com")
        recipient = self._user_create("recipient@example.com")
        project = self._project_create(sender)

        invite = self._create_invite(sender, recipient, project)

        request = self.factory.post(f"/invites/{invite.id}/accept/")
        force_authenticate(request, user=recipient)
        accept_response = InviteAccept.as_view()(request, pk=invite.id)

        self.assertEqual(accept_response.status_code, 200)
        invite.refresh_from_db()
        self.assertTrue(invite.is_accepted)

    def test_decline_invite_by_intended_user(self):
        sender = self._user_create("sender@example.com")
        recipient = self._user_create("recipient@example.com")
        project = self._project_create(sender)

        invite = self._create_invite(sender, recipient, project)

        request = self.factory.post(f"/invites/{invite.id}/decline/")
        force_authenticate(request, user=recipient)
        decline_response = InviteDecline.as_view()(request, pk=invite.id)

        self.assertEqual(decline_response.status_code, 200)
        invite.refresh_from_db()
        self.assertFalse(invite.is_accepted)

    def test_accept_decline_invite_by_unintended_user(self):
        sender = self._user_create("sender@example.com")
        recipient = self._user_create("recipient@example.com")
        unintended_user = self._user_create("unintended@example.com")
        project = self._project_create(sender)

        invite = self._create_invite(sender, recipient, project)

        accept_request = self.factory.post(f"/invites/{invite.id}/accept/")
        force_authenticate(accept_request, user=unintended_user)
        accept_response = InviteAccept.as_view()(accept_request, pk=invite.id)

        decline_request = self.factory.post(f"/invites/{invite.id}/decline/")
        force_authenticate(decline_request, user=unintended_user)
        decline_response = InviteDecline.as_view()(decline_request, pk=invite.id)

        self.assertNotEqual(accept_response.status_code, 200)
        self.assertNotEqual(decline_response.status_code, 200)

    def test_delete_invite_by_sender(self):
        sender = self._user_create("sender@example.com")
        recipient = self._user_create("recipient@example.com")
        project = self._project_create(sender)

        invite = self._create_invite(sender, recipient, project)

        request = self.factory.delete(f"/invites/{invite.id}/")
        force_authenticate(request, user=sender)
        delete_response = self.invite_detail_view(request, pk=invite.id)

        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(Invite.objects.filter(pk=invite.id).exists())

    def _project_create(self, user):
        request = self.factory.post("projects/", self.project_create_data)
        force_authenticate(request, user=user)

        response = self.project_list_view(request)
        project_id = response.data["id"]
        return Project.objects.get(pk=project_id)

    def _user_create(self, email):
        tmp_create_data = USER_CREATE_DATA.copy()
        tmp_create_data["email"] = email
        request = self.factory.post("auth/users/", tmp_create_data)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user

    def _create_invite(self, sender, recipient, project):
        invite_data = self.invite_create_data.copy()
        invite_data.update({"project": project.id, "user": recipient.id})

        request = self.factory.post("/invites/", invite_data, format="json")
        force_authenticate(request, user=sender)
        response = self.invite_list_view(request)

        return Invite.objects.get(pk=response.data["id"])
