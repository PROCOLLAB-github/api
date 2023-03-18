from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from tests.constants import USER_CREATE_DATA

from users.views import UserList
from users.models import CustomUser
from invites.views import InviteList, InviteDetail
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
        self._user_create("example2@gmail.com")
        self._project_create(user_main)
        self.invite_create_data["user"] = CustomUser.objects.values()[1]["id"]
        request = self.factory.post("invites/", self.invite_create_data, format="json")
        force_authenticate(request, user=user_main)

        response = self.invite_list_view(request)

        self.assertEqual(response.status_code, 201)

    def _project_create(self, user):
        request = self.factory.post("projects/", self.project_create_data)
        force_authenticate(request, user=user)

        response = self.project_list_view(request)
        self.assertEqual(response.status_code, 201)

    def _user_create(self, email):
        USER_CREATE_DATA["email"] = email
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user
