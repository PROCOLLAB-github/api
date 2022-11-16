from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from industries.models import Industry
from projects.models import Project
from users.models import CustomUser
from users.views import UserList
from vacancy.views import (
    VacancyList,
    VacancyDetail,
    VacancyResponseDetail,
    VacancyResponseList,
)


class VacancyTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user_list_view = UserList.as_view()
        self.vacancy_list_view = VacancyList.as_view()
        self.vacancy_detail_view = VacancyDetail.as_view()
        self.user_project_owner = self.user_create()
        self.vacancy_create_data = {
            "role": "Test",
            "required_skills": "Test",
            "description": "Test",
            "is_active": True,
            "project": Project.objects.create(
                name="Test",
                description="Test",
                industry=Industry.objects.create(name="Test"),
                step=1,
                leader=self.user_project_owner,
            ).id,
        }

    def test_vacancy_creation(self):
        request = self.factory.post("vacancy/", self.vacancy_create_data)
        force_authenticate(request, user=self.user_project_owner)
        response = self.vacancy_list_view(request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], "Test")
        self.assertEqual(response.data["required_skills"], "Test")
        self.assertEqual(response.data["description"], "Test")
        self.assertEqual(response.data["is_active"], True)
        self.assertEqual(response.data["project"], self.vacancy_create_data["project"])

    def user_create(self):
        request = self.factory.post(
            "auth/users/",
            {
                "email": "only_for_test@test.test",
                "password": "very_strong_password",
                "first_name": "Test",
                "last_name": "Test",
            },
        )
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user


class VacancyResponseTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user_list_view = UserList.as_view()
        self.vacancy_response_list_view = VacancyResponseList.as_view()
        self.vacancy_response_detail_view = VacancyResponseDetail.as_view()

    def user_create(self):
        request = self.factory.post(
            "auth/users/",
            {
                "email": "only_for_test@test.test",
                "password": "very_strong_password",
                "first_name": "Test",
                "last_name": "Test",
            },
        )
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user
