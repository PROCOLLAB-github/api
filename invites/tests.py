from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from projects.models import Project
from tests.constants import USER_CREATE_DATA

from users.views import UserList
from users.models import CustomUser
from invites.views import InviteList, InviteDetail
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

        self.invite_create_data["user"] = user2.id
        self.invite_create_data["project"] = project.id
        request = self.factory.post("invites/", self.invite_create_data, format="json")
        force_authenticate(request, user=user_main)

        response = self.invite_list_view(request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data["motivational_letter"],
            self.invite_create_data["motivational_letter"],
        )
        self.assertEqual(
            response.data["project"]["id"], self.invite_create_data["project"]
        )
        self.assertEqual(response.data["role"], self.invite_create_data["role"])
        self.assertEqual(
            response.data["is_accepted"], self.invite_create_data["is_accepted"]
        )

    def test_invites_creation_with_empty_text(self):
        user_main = self._user_create("example@gmail.com")
        user2 = self._user_create("example2@gmail.com")
        project = self._project_create(user_main)

        self.invite_create_data["user"] = user2.id
        self.invite_create_data["project"] = project.id
        self.invite_create_data["motivational_letter"] = None
        request = self.factory.post("invites/", self.invite_create_data, format="json")
        force_authenticate(request, user=user_main)

        response = self.invite_list_view(request)

        self.assertEqual(response.status_code, 201)

    def test_invites_update(self):
        user_main = self._user_create("example@gmail.com")
        user2 = self._user_create("example2@gmail.com")
        project = self._project_create(user_main)

        self.invite_create_data["user"] = user2.id
        self.invite_create_data["project"] = project.id
        request = self.factory.post("invites/", self.invite_create_data, format="json")
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

        self.invite_create_data = {}

        request = self.factory.post("invites/", self.invite_create_data, format="json")
        force_authenticate(request, user=user_main)
        response = self.invite_list_view(request)

        self.assertEqual(response.status_code, 400)

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
