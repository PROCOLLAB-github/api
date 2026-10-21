from unittest.mock import patch
from types import SimpleNamespace

from django.test import TestCase
from rest_framework.test import APIClient

from vacancy.models import Vacancy, VacancyResponse
from vacancy.serializers import ProjectVacancyListSerializer
from projects.serializers import ProjectDetailSerializer
from vacancy.tests.helpers import (
    create_project,
    create_user,
    create_vacancy,
    create_vacancy_response,
    vacancy_payload,
)


class VacancyArchiveAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.project = create_project()
        self.vacancy = create_vacancy(project=self.project)
        self.url = f"/vacancies/{self.vacancy.pk}/"
        self.client.force_authenticate(self.project.leader)

    @patch("vacancy.lifecycle.send_email.delay")
    def test_archive_preserves_history_and_notifies_pending_once(self, email):
        pending = create_vacancy_response(vacancy=self.vacancy)
        accepted = create_vacancy_response(vacancy=self.vacancy, is_approved=True)
        rejected = create_vacancy_response(vacancy=self.vacancy, is_approved=False)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(self.url, {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        self.assertEqual(response.data["total_response_count"], 3)
        self.assertEqual(response.data["response_count"], 0)
        self.assertIsNotNone(response.data["datetime_closed"])
        for item in [pending, accepted, rejected]:
            item.refresh_from_db()
        self.assertFalse(pending.is_approved)
        self.assertTrue(accepted.is_approved)
        self.assertFalse(rejected.is_approved)
        email.assert_called_once()
        with self.captureOnCommitCallbacks(execute=True):
            again = self.client.patch(self.url, {"is_active": False}, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data["datetime_closed"], response.data["datetime_closed"])
        email.assert_called_once()

    def test_reopen_preserves_decisions_and_clears_closed_date(self):
        self.vacancy.is_active = False
        self.vacancy.save()
        response = create_vacancy_response(vacancy=self.vacancy, is_approved=False)
        result = self.client.patch(self.url, {"is_active": True}, format="json")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.data["is_active"])
        self.assertIsNone(result.data["datetime_closed"])
        response.refresh_from_db()
        self.assertFalse(response.is_approved)

    def test_reopen_requires_public_published_project(self):
        self.vacancy.is_active = False
        self.vacancy.save()
        for draft, public in [(True, True), (False, False)]:
            self.project.draft = draft
            self.project.is_public = public
            self.project.save()
            self.vacancy.is_active = False
            self.vacancy.save()
            response = self.client.patch(self.url, {"is_active": True}, format="json")
            self.assertEqual(response.status_code, 400)
            self.vacancy.refresh_from_db()
            self.assertFalse(self.vacancy.is_active)

    def test_delete_blocks_all_response_states_in_both_lists(self):
        for active in [True, False]:
            self.vacancy.is_active = active
            self.vacancy.save()
            for decision in [None, True, False]:
                reply = create_vacancy_response(
                    vacancy=self.vacancy, is_approved=decision
                )
                response = self.client.delete(self.url)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(str(response.data["code"]), "vacancy_has_responses")
                self.assertTrue(Vacancy.objects.filter(pk=self.vacancy.pk).exists())
                self.assertTrue(VacancyResponse.objects.filter(pk=reply.pk).exists())
                reply.delete()

    def test_delete_empty_vacancy(self):
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.assertFalse(Vacancy.objects.filter(pk=self.vacancy.pk).exists())

    def test_invalid_archive_is_atomic(self):
        reply = create_vacancy_response(vacancy=self.vacancy)
        response = self.client.patch(
            self.url, {"is_active": False, "role": ""}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.vacancy.refresh_from_db()
        reply.refresh_from_db()
        self.assertTrue(self.vacancy.is_active)
        self.assertIsNone(reply.is_approved)

    def test_edit_without_lifecycle_field_keeps_pending_responses(self):
        reply = create_vacancy_response(vacancy=self.vacancy)
        response = self.client.put(self.url, vacancy_payload(self.project), format="json")
        self.assertEqual(response.status_code, 200)
        reply.refresh_from_db()
        self.assertIsNone(reply.is_approved)

    def test_foreign_user_cannot_archive_reopen_or_delete(self):
        self.client.force_authenticate(create_user())
        for method, payload in [
            ("patch", {"is_active": False}),
            ("patch", {"is_active": True}),
            ("delete", None),
        ]:
            response = getattr(self.client, method)(self.url, payload, format="json")
            self.assertEqual(response.status_code, 403)
        self.vacancy.refresh_from_db()
        self.assertTrue(self.vacancy.is_active)

    def test_pending_count_remains_compatible_with_total_history(self):
        create_vacancy_response(vacancy=self.vacancy)
        create_vacancy_response(vacancy=self.vacancy, is_approved=False)
        data = ProjectVacancyListSerializer(self.vacancy).data
        self.assertEqual(data["response_count"], 1)
        self.assertEqual(data["total_response_count"], 2)

    def test_embedded_archive_visible_only_to_managers(self):
        archived = create_vacancy(project=self.project, is_active=False)
        for user, expected in [
            (self.project.leader, {self.vacancy.pk, archived.pk}),
            (create_user(), {self.vacancy.pk}),
            (None, {self.vacancy.pk}),
        ]:
            serializer = ProjectDetailSerializer(
                context={"request": SimpleNamespace(user=user)}
            )
            data = serializer.get_vacancies(self.project)
            self.assertEqual({item["id"] for item in data}, expected)

    def test_invalid_skills_do_not_destroy_existing_skills_or_close_vacancy(self):
        from vacancy.tests.helpers import create_skill

        skill = create_skill()
        self.vacancy.required_skills.create(skill=skill)
        response = self.client.patch(
            self.url,
            {"is_active": False, "required_skills_ids": [999999]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.vacancy.refresh_from_db()
        self.assertTrue(self.vacancy.is_active)
        self.assertEqual(self.vacancy.required_skills.get().skill_id, skill.pk)
