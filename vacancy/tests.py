from collections import OrderedDict

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from industries.models import Industry
from projects.models import Project
from tests.constants import USER_CREATE_DATA
from users.models import CustomUser
from users.views import UserList
from vacancy.constants import (
    WorkExperience,
    WorkSchedule,
    WorkFormat,
)
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

        self.created_project = Project.objects.create(
            name="Test",
            description="Test",
            industry=Industry.objects.create(name="Test"),
            step=1,
            leader=self.user_project_owner,
        )
        self.vacancy_create_data = {
            "role": "Test",
            "required_skills_ids": [1, 15],
            "description": "Test",
            "is_active": True,
            "project": self.created_project.id,
            "required_experience": WorkExperience.NO_EXPERIENCE.value,
            "work_schedule": WorkSchedule.FULL_TIME.value,
            "work_format": WorkFormat.REMOTE.value,
            "salary": 100,
        }

    def test_vacancy_creation(self):
        request = self.factory.post("vacancy/", self.vacancy_create_data)
        force_authenticate(request, user=self.user_project_owner)
        response = self.vacancy_list_view(request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], "Test")
        self.assertEqual(
            response.data["required_skills"],
            [
                OrderedDict(
                    [
                        ("id", 1),
                        ("name", "Ведение социальных сетей"),
                        ("category", OrderedDict([("id", 1), ("name", "Маркетинг")])),
                    ]
                ),
                OrderedDict(
                    [
                        ("id", 15),
                        ("name", "MS Office"),
                        ("category", OrderedDict([("id", 1), ("name", "Маркетинг")])),
                    ]
                ),
            ],
        )
        self.assertEqual(response.data["description"], "Test")
        self.assertEqual(response.data["is_active"], not self.created_project.draft)
        self.assertEqual(response.data["project"]["id"], self.vacancy_create_data["project"])
        self.assertEqual(response.data["required_experience"], WorkExperience.NO_EXPERIENCE.value)
        self.assertEqual(response.data["work_schedule"], WorkSchedule.FULL_TIME.value)
        self.assertEqual(response.data["work_format"], WorkFormat.REMOTE.value)
        self.assertEqual(response.data["salary"], 100)

    def user_create(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
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
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user
