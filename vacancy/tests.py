from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from industries.models import Industry
from projects.models import Project, Collaborator
from tests.constants import USER_CREATE_DATA
from users.models import CustomUser
from users.views import UserList
from vacancy.views import (
    VacancyList,
    VacancyDetail,
    VacancyResponseList,
    VacancyResponseAccept,
    VacancyResponseDecline,
)
from vacancy.models import Vacancy, VacancyResponse

ANOTHER_USER_CREATE_DATA = {
    "email": "another_user@test.com",
    "password": "test_password",
    "first_name": "Сергей",
    "last_name": "Сергеев",
    "birthday": "2000-01-02",
}


class TestUtils:
    @staticmethod
    def create_user(factory, user_list_view, user_create_data):
        request = factory.post("auth/users/", user_create_data)
        response = user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user

    @staticmethod
    def create_project(user, name="Test Project", description="Test Description"):
        industry = Industry.objects.create(name="Test")
        return Project.objects.create(
            name=name,
            description=description,
            industry=industry,
            step=1,
            leader=user,
        )

    @staticmethod
    def create_vacancy(
        project,
        role="Test Role",
        required_skills=["Test Skill"],
        description="Test Description",
    ):
        return Vacancy.objects.create(
            role=role,
            required_skills=required_skills,
            description=description,
            is_active=True,
            project=project,
        )

    @staticmethod
    def create_vacancy_response(user, vacancy, why_me="Отклик на вакансию!"):
        return VacancyResponse.objects.create(user=user, vacancy=vacancy, why_me=why_me)


class VacancyTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user_list_view = UserList.as_view()
        self.vacancy_list_view = VacancyList.as_view()
        self.vacancy_response_list_view = VacancyResponseList.as_view()
        self.vacancy_response_accept_view = VacancyResponseAccept.as_view()
        self.vacancy_response_decline_view = VacancyResponseDecline.as_view()
        self.vacancy_detail_view = VacancyDetail.as_view()

        self.user_project_owner = TestUtils.create_user(
            self.factory, self.user_list_view, USER_CREATE_DATA
        )
        self.project = TestUtils.create_project(self.user_project_owner)
        self.vacancy = TestUtils.create_vacancy(self.project)

        self.another_user = TestUtils.create_user(
            self.factory, self.user_list_view, ANOTHER_USER_CREATE_DATA
        )

    def test_vacancy_creation(self):
        self.assertEqual(self.vacancy.role, "Test Role")
        self.assertEqual(self.vacancy.required_skills, ["Test Skill"])
        self.assertEqual(self.vacancy.description, "Test Description")
        self.assertTrue(self.vacancy.is_active)
        self.assertEqual(self.vacancy.project, self.project)

    def test_response_by_project_owner(self):
        url = f"/vacancies/responses/{self.vacancy.id}/"
        data = {
            "why_me": "Владелец проекта откликается на свою же вакансию.",
            "user_id": self.user_project_owner.id,
            "vacancy": self.vacancy.id,
        }
        request = self.factory.post(url, data)
        force_authenticate(request, user=self.user_project_owner)
        response = self.vacancy_response_list_view(request, vacancy_id=self.vacancy.id)
        self.assertEqual(response.status_code, 201)

    def test_response_by_user(self):
        url = f"/vacancies/responses/{self.vacancy.id}/"
        data = {
            "why_me": "Пользователь откликается на вакансию",
            "user_id": self.another_user.id,
            "vacancy": self.vacancy.id,
        }
        request = self.factory.post(url, data)
        force_authenticate(request, user=self.another_user)
        response = self.vacancy_response_list_view(request, vacancy_id=self.vacancy.id)
        self.assertEqual(response.status_code, 201)

    def test_response_by_unauthenticated_user(self):
        url = f"/vacancies/responses/{self.vacancy.id}/"
        data = {"why_me": "Без авторизации"}
        request = self.factory.post(url, data)
        response = self.vacancy_response_list_view(request, vacancy_id=self.vacancy.id)
        self.assertEqual(response.status_code, 401)

    def test_accept_vacancy_response_by_project_owner(self):
        vacancy_response = TestUtils.create_vacancy_response(
            self.another_user, self.vacancy
        )

        url = f"/vacancy/responses/{vacancy_response.id}/accept/"
        request = self.factory.post(url)
        force_authenticate(request, user=self.user_project_owner)
        response = self.vacancy_response_accept_view(request, pk=vacancy_response.id)
        self.assertEqual(response.status_code, 200)

        vacancy_response.refresh_from_db()
        self.assertTrue(vacancy_response.is_approved)
        self.assertTrue(
            Collaborator.objects.filter(
                user=self.another_user, project=self.vacancy.project
            ).exists()
        )

    def test_accept_vacancy_response_by_user(self):
        vacancy_response = TestUtils.create_vacancy_response(
            self.another_user, self.vacancy
        )

        url = f"/vacancy/responses/{vacancy_response.id}/accept/"
        request = self.factory.post(url)
        force_authenticate(request, user=self.another_user)
        response = self.vacancy_response_accept_view(request, pk=vacancy_response.id)
        self.assertEqual(response.status_code, 403)

        vacancy_response.refresh_from_db()
        self.assertFalse(vacancy_response.is_approved)
        self.assertFalse(
            Collaborator.objects.filter(
                user=self.another_user, project=self.vacancy.project
            ).exists()
        )

    def test_accept_vacancy_response_by_unauthenticated_user(self):
        vacancy_response = TestUtils.create_vacancy_response(
            self.another_user, self.vacancy
        )

        url = f"/vacancy/responses/{vacancy_response.id}/accept/"
        request = self.factory.post(url)
        response = self.vacancy_response_accept_view(request, pk=vacancy_response.id)
        self.assertEqual(response.status_code, 401)

        vacancy_response.refresh_from_db()
        self.assertFalse(vacancy_response.is_approved)
        self.assertFalse(
            Collaborator.objects.filter(
                user=self.another_user, project=self.vacancy.project
            ).exists()
        )

    def test_decline_vacancy_response_by_project_owner(self):
        vacancy_response = TestUtils.create_vacancy_response(
            self.another_user, self.vacancy
        )

        url = f"/vacancy/responses/{vacancy_response.id}/decline/"
        request = self.factory.post(url)
        force_authenticate(request, user=self.user_project_owner)
        response = self.vacancy_response_decline_view(request, pk=vacancy_response.id)
        self.assertEqual(response.status_code, 200)

        vacancy_response.refresh_from_db()
        self.assertFalse(vacancy_response.is_approved)
        self.assertFalse(
            Collaborator.objects.filter(
                user=self.another_user, project=self.vacancy.project
            ).exists()
        )

    def test_decline_vacancy_response_by_user(self):
        vacancy_response = TestUtils.create_vacancy_response(
            self.another_user, self.vacancy
        )

        url = f"/vacancy/responses/{vacancy_response.id}/decline/"
        request = self.factory.post(url)
        force_authenticate(request, user=self.another_user)
        response = self.vacancy_response_decline_view(request, pk=vacancy_response.id)
        self.assertEqual(response.status_code, 403)

        vacancy_response.refresh_from_db()
        self.assertIsNone(vacancy_response.is_approved)
        self.assertFalse(
            Collaborator.objects.filter(
                user=self.another_user, project=self.vacancy.project
            ).exists()
        )

    def test_decline_vacancy_response_by_unauthenticated_user(self):
        vacancy_response = TestUtils.create_vacancy_response(
            self.another_user, self.vacancy
        )

        url = f"/vacancy/responses/{vacancy_response.id}/decline/"
        request = self.factory.post(url)
        response = self.vacancy_response_decline_view(request, pk=vacancy_response.id)
        self.assertEqual(response.status_code, 401)

        vacancy_response.refresh_from_db()
        self.assertIsNone(vacancy_response.is_approved)
        self.assertFalse(
            Collaborator.objects.filter(
                user=self.another_user, project=self.vacancy.project
            ).exists()
        )

    def test_vacancy_deletion_by_owner(self):
        delete_request = self.factory.delete(f"/vacancy/{self.vacancy.id}/")
        force_authenticate(delete_request, user=self.user_project_owner)
        delete_response = self.vacancy_detail_view(delete_request, pk=self.vacancy.id)

        self.assertEqual(delete_response.status_code, 204)
        with self.assertRaises(Vacancy.DoesNotExist):
            Vacancy.objects.get(id=self.vacancy.id)

    def test_vacancy_deletion_by_user(self):
        delete_request = self.factory.delete(f"/vacancy/{self.vacancy.id}/")
        force_authenticate(delete_request, user=self.another_user)
        delete_response = self.vacancy_detail_view(delete_request, pk=self.vacancy.id)

        self.assertEqual(delete_response.status_code, 403)
        self.assertTrue(Vacancy.objects.filter(id=self.vacancy.id).exists())

    def test_vacancy_deletion_by_unauthenticated_user(self):
        delete_request = self.factory.delete(f"/vacancy/{self.vacancy.id}/")
        delete_response = self.vacancy_detail_view(delete_request, pk=self.vacancy.id)

        self.assertEqual(delete_response.status_code, 401)
        self.assertTrue(Vacancy.objects.filter(id=self.vacancy.id).exists())
