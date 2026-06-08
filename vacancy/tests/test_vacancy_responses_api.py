from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from projects.models import Collaborator
from vacancy.models import VacancyResponse
from vacancy.tests.helpers import (
    create_project,
    create_user,
    create_user_file,
    create_vacancy,
    create_vacancy_response,
)


class VacancyResponseAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("vacancy.views.send_email.delay")
    def test_user_can_apply_to_active_vacancy(self, send_email_delay):
        user = create_user(prefix="applicant")
        vacancy = create_vacancy(role="Apply vacancy", is_active=True)
        file = create_user_file(user=user)
        self.client.force_authenticate(user)

        response = self.client.post(
            f"/vacancies/{vacancy.id}/responses/",
            {
                "why_me": "Есть опыт",
                "accompanying_file": file.link,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        vacancy_response = VacancyResponse.objects.get()
        self.assertEqual(vacancy_response.user, user)
        self.assertEqual(vacancy_response.vacancy, vacancy)
        self.assertEqual(vacancy_response.accompanying_file, file)
        send_email_delay.assert_called_once()

    @patch("vacancy.views.send_email.delay")
    def test_user_cannot_apply_to_closed_vacancy(self, send_email_delay):
        user = create_user(prefix="applicant")
        vacancy = create_vacancy(is_active=False)
        self.client.force_authenticate(user)

        response = self.client.post(
            f"/vacancies/{vacancy.id}/responses/",
            {"why_me": "Есть опыт"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(VacancyResponse.objects.exists())
        send_email_delay.assert_not_called()

    @patch("vacancy.views.send_email.delay")
    def test_user_cannot_apply_twice_to_same_vacancy(self, send_email_delay):
        user = create_user(prefix="applicant")
        vacancy = create_vacancy()
        create_vacancy_response(user=user, vacancy=vacancy)
        self.client.force_authenticate(user)

        response = self.client.post(
            f"/vacancies/{vacancy.id}/responses/",
            {"why_me": "Повторный отклик"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(VacancyResponse.objects.count(), 1)
        send_email_delay.assert_not_called()

    def test_response_list_returns_responses_for_vacancy(self):
        vacancy = create_vacancy()
        target_response = create_vacancy_response(vacancy=vacancy, why_me="Target")
        create_vacancy_response(why_me="Other")

        response = self.client.get(f"/vacancies/{vacancy.id}/responses/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [target_response.id])
        self.assertEqual(response.data[0]["why_me"], "Target")

    def test_current_user_responses_returns_only_own_responses(self):
        user = create_user(prefix="applicant")
        own_response = create_vacancy_response(user=user)
        create_vacancy_response()
        self.client.force_authenticate(user)

        response = self.client.get("/vacancies/responses/self")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [own_response.id],
        )

    def test_response_detail_returns_full_file_info_for_read(self):
        user = create_user(prefix="applicant")
        file = create_user_file(user=user)
        vacancy_response = create_vacancy_response(user=user, accompanying_file=file)
        self.client.force_authenticate(user)

        response = self.client.get(f"/vacancies/responses/{vacancy_response.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["accompanying_file"]["link"], file.link)


class VacancyResponseDecisionAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("vacancy.views.send_email.delay")
    def test_project_leader_can_accept_response(self, send_email_delay):
        leader = create_user(prefix="leader")
        applicant = create_user(prefix="applicant")
        project = create_project(leader=leader, draft=False)
        vacancy = create_vacancy(project=project, is_active=True, role="Designer")
        vacancy_response = create_vacancy_response(user=applicant, vacancy=vacancy)
        self.client.force_authenticate(leader)

        response = self.client.post(
            f"/vacancies/responses/{vacancy_response.id}/accept/"
        )

        vacancy_response.refresh_from_db()
        vacancy.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(vacancy_response.is_approved)
        self.assertFalse(vacancy.is_active)
        self.assertIsNotNone(vacancy.datetime_closed)
        self.assertTrue(
            Collaborator.objects.filter(
                project=project,
                user=applicant,
                role="Designer",
            ).exists()
        )
        self.assertEqual(send_email_delay.call_args.args[0]["user_id"], applicant.id)

    @patch("vacancy.views.send_email.delay")
    def test_project_leader_can_decline_response(self, send_email_delay):
        leader = create_user(prefix="leader")
        applicant = create_user(prefix="applicant")
        project = create_project(leader=leader)
        vacancy = create_vacancy(project=project)
        vacancy_response = create_vacancy_response(user=applicant, vacancy=vacancy)
        self.client.force_authenticate(leader)

        response = self.client.post(
            f"/vacancies/responses/{vacancy_response.id}/decline/"
        )

        vacancy_response.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(vacancy_response.is_approved)
        self.assertEqual(send_email_delay.call_args.args[0]["user_id"], applicant.id)

    @patch("vacancy.views.send_email.delay")
    def test_non_leader_cannot_accept_response(self, send_email_delay):
        vacancy_response = create_vacancy_response()
        outsider = create_user(prefix="outsider")
        self.client.force_authenticate(outsider)

        response = self.client.post(
            f"/vacancies/responses/{vacancy_response.id}/accept/"
        )

        vacancy_response.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIsNone(vacancy_response.is_approved)
        send_email_delay.assert_not_called()

    @patch("vacancy.views.send_email.delay")
    def test_cannot_accept_or_decline_already_processed_response(self, send_email_delay):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        vacancy = create_vacancy(project=project)
        vacancy_response = create_vacancy_response(
            vacancy=vacancy,
            is_approved=True,
        )
        self.client.force_authenticate(leader)

        accept_response = self.client.post(
            f"/vacancies/responses/{vacancy_response.id}/accept/"
        )
        decline_response = self.client.post(
            f"/vacancies/responses/{vacancy_response.id}/decline/"
        )

        self.assertEqual(accept_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(decline_response.status_code, status.HTTP_400_BAD_REQUEST)
        send_email_delay.assert_not_called()
