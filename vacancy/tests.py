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
    VacancyResponseDetail,
    VacancyResponseList,
    VacancyResponseAccept,
    VacancyResponseDecline,
)
from vacancy.models import Vacancy, VacancyResponse


class VacancyTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user_list_view = UserList.as_view()
        self.vacancy_list_view = VacancyList.as_view()
        self.vacancy_detail_view = VacancyDetail.as_view()
        self.user_project_owner = self.user_create()
        self.vacancy_create_data = {
            "role": "Test",
            "required_skills": ["Test"],
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
        self.assertEqual(response.data["required_skills"], ["Test"])
        self.assertEqual(response.data["description"], "Test")
        self.assertEqual(response.data["is_active"], True)
        self.assertEqual(response.data["project"], self.vacancy_create_data["project"])

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
        self.user = self.user_create()
        self.project = self.project_create(self.user)
        self.vacancy = self.vacancy_create(self.project)
        self.another_user_create_data = {
            "email": "another_user@test.com",
            "password": "test_password",
            "first_name": "Сергей",
            "last_name": "Сергеев",
            "birthday": "2000-01-02",
        }
        self.another_user = self.second_user_create()

    def user_create(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user

    def second_user_create(self):
        request = self.factory.post("auth/users/", self.another_user_create_data)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user

    def project_create(self, user):
        project = Project.objects.create(
            name="Test Project",
            description="Test Description",
            leader=user,
        )
        return project

    def vacancy_create(self, project):
        vacancy = Vacancy.objects.create(
            role="Test Role",
            required_skills="Test Skill",
            description="Test Description",
            is_active=True,
            project=project,
        )
        return vacancy

    def test_response_by_project_owner(self):
        url = f"/vacancies/responses/{self.vacancy.id}/"
        data = {
            "why_me": "Владелец проекта откликается на свою же вакансию. ",
            "user_id": self.user.id,
            "vacancy": self.vacancy.id,
        }
        request = self.factory.post(url, data)
        force_authenticate(request, user=self.user)
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


class VacancyResponseAcceptDeclineTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user_list_view = UserList.as_view()
        self.vacancy_response_list_view = VacancyResponseList.as_view()
        self.vacancy_response_detail_view = VacancyResponseDetail.as_view()
        self.vacancy_response_accept_view = VacancyResponseAccept.as_view()
        self.vacancy_response_decline_view = VacancyResponseDecline.as_view()
        self.user_project_owner = self.user_create()
        self.project = self.project_create(self.user_project_owner)
        self.vacancy = self.vacancy_create(self.project)
        self.another_user_create_data = {
            "email": "another_user@test.com",
            "password": "test_password",
            "first_name": "Сергей",
            "last_name": "Сергеев",
            "birthday": "2000-01-02",
        }
        self.another_user = self.second_user_create()

    def project_create(self, user):
        industry = Industry.objects.create(name="Test")
        project = Project.objects.create(
            name="Test",
            description="Test",
            industry=industry,
            step=1,
            leader=user,
        )
        return project

    def vacancy_create(self, project):
        vacancy = Vacancy.objects.create(
            role="Test Role",
            required_skills="Test Skill",
            description="Test Description",
            is_active=True,
            project=project,
        )
        return vacancy

    def user_create(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user

    def second_user_create(self):
        request = self.factory.post("auth/users/", self.another_user_create_data)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user

    def create_vacancy_response(self):
        return VacancyResponse.objects.create(
            user=self.another_user, vacancy=self.vacancy, why_me="Отклик на вакансию!"
        )

    def test_accept_vacancy_response_by_project_owner(self):
        vacancy_response = self.create_vacancy_response()

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
        vacancy_response = self.create_vacancy_response()

        url = f"/vacancy/responses/{vacancy_response.id}/accept/"
        request = self.factory.post(url)
        force_authenticate(request, user=self.another_user)
        response = self.vacancy_response_accept_view(request, pk=vacancy_response.id)
        self.assertEqual(response.status_code, 403)

        vacancy_response.refresh_from_db()
        self.assertIsNone(vacancy_response.is_approved)

        self.assertFalse(
            Collaborator.objects.filter(
                user=self.another_user, project=self.vacancy.project
            ).exists()
        )

    def test_accept_vacancy_response_by_unauthenticated_user(self):
        vacancy_response = self.create_vacancy_response()

        url = f"/vacancy/responses/{vacancy_response.id}/accept/"
        request = self.factory.post(url)
        response = self.vacancy_response_accept_view(request, pk=vacancy_response.id)
        self.assertEqual(response.status_code, 401)

        vacancy_response.refresh_from_db()
        self.assertIsNone(vacancy_response.is_approved)
        self.assertFalse(
            Collaborator.objects.filter(
                user=self.another_user, project=self.vacancy.project
            ).exists()
        )

    def test_decline_vacancy_response_by_project_owner(self):
        vacancy_response = self.create_vacancy_response()

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
        vacancy_response = self.create_vacancy_response()

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
        vacancy_response = self.create_vacancy_response()

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


class VacancyDeleteTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user_list_view = UserList.as_view()
        self.vacancy_list_view = VacancyList.as_view()
        self.vacancy_detail_view = VacancyDetail.as_view()
        self.user_project_owner = self.user_create()
        self.vacancy_create_data = {
            "role": "Test",
            "required_skills": ["Test"],
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
        self.another_user_create_data = {
            "email": "another_user@test.com",
            "password": "test_password",
            "first_name": "Сергей",
            "last_name": "Сергеев",
            "birthday": "2000-01-02",
        }
        self.another_user = self.second_user_create()

    def user_create(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user

    def second_user_create(self):
        request = self.factory.post("auth/users/", self.another_user_create_data)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user

    def test_vacancy_deletion_by_owner(self):
        create_request = self.factory.post("/vacancy/", self.vacancy_create_data)
        force_authenticate(create_request, user=self.user_project_owner)
        create_response = self.vacancy_list_view(create_request)

        vacancy_id = create_response.data["id"]

        delete_request = self.factory.delete(f"/vacancy/{vacancy_id}/")
        force_authenticate(delete_request, user=self.user_project_owner)

        delete_response = self.vacancy_detail_view(delete_request, pk=vacancy_id)

        self.assertEqual(delete_response.status_code, 204)
        with self.assertRaises(Vacancy.DoesNotExist):
            Vacancy.objects.get(id=vacancy_id)

    def test_vacancy_deletion_by_user(self):
        create_request = self.factory.post("/vacancy/", self.vacancy_create_data)
        force_authenticate(create_request, user=self.user_project_owner)
        create_response = self.vacancy_list_view(create_request)
        vacancy_id = create_response.data["id"]

        delete_request = self.factory.delete(f"/vacancy/{vacancy_id}/")
        force_authenticate(delete_request, user=self.another_user)
        delete_response = self.vacancy_detail_view(delete_request, pk=vacancy_id)

        self.assertEqual(delete_response.status_code, 403)
        self.assertTrue(Vacancy.objects.filter(id=vacancy_id).exists())

    def test_vacancy_deletion_by_unauthenticated_user(self):
        create_request = self.factory.post("/vacancy/", self.vacancy_create_data)
        force_authenticate(create_request, user=self.user_project_owner)
        create_response = self.vacancy_list_view(create_request)
        vacancy_id = create_response.data["id"]

        delete_request = self.factory.delete(f"/vacancy/{vacancy_id}/")
        delete_response = self.vacancy_detail_view(delete_request, pk=vacancy_id)

        self.assertEqual(delete_response.status_code, 401)

        self.assertTrue(Vacancy.objects.filter(id=vacancy_id).exists())
