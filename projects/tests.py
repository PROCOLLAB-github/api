from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from industries.models import Industry
from projects.models import Project
from projects.views import ProjectList, ProjectDetail
from tests.constants import USER_CREATE_DATA
from users.models import CustomUser
from users.views import UserList


class ProjectTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.project_list_view = ProjectList.as_view()
        self.user_list_view = UserList.as_view()
        self.project_detail_view = ProjectDetail.as_view()
        self.project_create_data = {
            "name": "Test",
            "description": "Test",
            "industry": Industry.objects.create(name="Test").id,
            "step": 1,
        }

    def test_project_creation(self):
        user = self.user_create()
        request = self.factory.post("projects/", self.project_create_data)
        force_authenticate(request, user=user)

        response = self.project_list_view(request)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "Test")
        self.assertEqual(response.data["description"], "Test")
        self.assertEqual(response.data["industry"], 1)

    def test_project_creation_with_wrong_data(self):
        user = self.user_create()
        request = self.factory.post(
            "projects/",
            {
                "name": "T" * 257,
                "description": "Test",
                "industry": Industry.objects.create(name="Test").id,
                "step": 1,
            },
        )
        force_authenticate(request, user=user)
        response = self.project_list_view(request)
        self.assertEqual(response.status_code, 400)

    def test_project_update(self):
        user = self.user_create()
        request = self.factory.post("projects/", self.project_create_data)
        force_authenticate(request, user=user)

        response = self.project_list_view(request)
        project_id = response.data["id"]
        project = Project.objects.get(id=project_id)

        request = self.factory.patch(f"projects/{project.pk}/", {"name": "Test2"})
        force_authenticate(request, user=user)
        response = self.project_detail_view(request, pk=project.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Test2")

    def user_create(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user
