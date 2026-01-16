from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from tests.constants import USER_CREATE_DATA

from projects.models import Collaborator, Project
from users.models import CustomUser
from users.views import UserLeaderProjectsList, UserList, UserDetail


class UserTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user_list_view = UserList.as_view()
        self.user_detail_view = UserDetail.as_view()
        self.user_leader_projects_view = UserLeaderProjectsList.as_view()

    def test_user_creation(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["email"], "only_for_test@test.test")
        self.assertEqual(response.data["is_active"], False)

    def test_user_creation_with_wrong_data(self):
        request = self.factory.post(
            "auth/users/",
            {
                "email": "qwe",
                "password": "qwe",
                "first_name": "qwe",
                "last_name": "qwe",
            },
        )
        response = self.user_list_view(request)
        self.assertEqual(response.status_code, 400)

    def test_user_creation_with_existing_email(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        self.assertEqual(response.status_code, 201)
        response = self.user_list_view(request)
        self.assertEqual(response.status_code, 400)

    def test_user_update(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)

        request = self.factory.get(f"auth/users/{user.pk}/")
        response = self.user_detail_view(request, pk=user.pk)
        self.assertEqual(response.status_code, 401)  # Unauthorized

        force_authenticate(request, user=user)
        response = self.user_detail_view(request, pk=user.pk)
        self.assertEqual(response.status_code, 200)

        request = self.factory.patch(f"auth/users/{user.pk}/", {"first_name": "Сергей"})
        force_authenticate(request, user=user)
        response = self.user_detail_view(request, pk=user.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["first_name"], "Сергей")

    def test_user_leader_projects_list(self):
        leader = self._user_create("leader@example.com")
        collaborator = self._user_create("collaborator@example.com")

        leader_project = Project.objects.create(name="Leader project", leader=leader)
        second_leader_project = Project.objects.create(
            name="Leader project 2", leader=leader, draft=False
        )
        other_project = Project.objects.create(name="Other project", leader=collaborator)
        Collaborator.objects.create(user=leader, project=other_project, role="Member")

        request = self.factory.get("users/projects/leader/")
        force_authenticate(request, user=leader)
        response = self.user_leader_projects_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        returned_ids = {item["id"] for item in response.data["results"]}
        self.assertSetEqual(
            returned_ids, {leader_project.id, second_leader_project.id}
        )

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
