from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from projects.models import Collaborator
from notifications.models import Notification
from vacancy.constants import WorkExperience, WorkFormat, WorkSchedule
from vacancy.models import Vacancy, VacancyResponse
from vacancy.tests.helpers import (
    create_project,
    create_skill,
    create_user,
    create_user_file,
    create_vacancy,
    create_vacancy_response,
)


PRIVATE_FIELDS = {
    "auth_token",
    "date_joined",
    "email",
    "groups",
    "phone",
    "phone_number",
    "birthday",
    "is_staff",
    "is_superuser",
    "last_login",
    "onboarding_stage",
    "password",
    "user_permissions",
}


def assert_private_fields_absent(test_case, value):
    if isinstance(value, dict):
        test_case.assertTrue(PRIVATE_FIELDS.isdisjoint(value))
        for nested in value.values():
            assert_private_fields_absent(test_case, nested)
    elif isinstance(value, list):
        for nested in value:
            assert_private_fields_absent(test_case, nested)


class VacancyCatalogContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_catalog_isolated_to_active_public_published_projects(self):
        visible = create_vacancy(role="Visible")
        create_vacancy(project=create_project(draft=True), role="Draft")
        create_vacancy(project=create_project(is_public=False), role="Private")
        create_vacancy(role="Closed", is_active=False)

        response = self.client.get("/vacancies/", {"is_active": "false"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])
        response = self.client.get("/vacancies/")
        self.assertEqual([item["id"] for item in response.data["results"]], [visible.id])

    def test_search_covers_role_specialization_description_and_project_name(self):
        project = create_project(name="арктическая платформа")
        vacancy = create_vacancy(project=project, role="Python инженер")
        Vacancy.objects.filter(pk=vacancy.pk).update(
            specialization="Data science",
            description="Разработка рекомендательной системы",
        )
        for search in ("python", "DATA SCIENCE", "рекомендательной", "арктическая"):
            with self.subTest(search=search):
                response = self.client.get("/vacancies/", {"search": f"  {search}  "})
                self.assertEqual(
                    [item["id"] for item in response.data["results"]],
                    [vacancy.id],
                )

    def test_filters_and_limit_offset_pagination(self):
        target = create_vacancy(
            required_experience=WorkExperience.FROM_THREE_YEARS.name.lower(),
            work_format=WorkFormat.HYBRID.name.lower(),
            work_schedule=WorkSchedule.PART_TIME.name.lower(),
            salary=180000,
            city="Казань",
        )
        create_vacancy(salary=90000)

        response = self.client.get(
            "/vacancies/",
            {
                "required_experience": "from_three_years",
                "work_format": "hybrid",
                "work_schedule": "part_time",
                "salary_min": "150000",
                "salary_max": "200000",
                "limit": "1",
                "offset": "0",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], target.id)
        self.assertEqual(response.data["results"][0]["city"], "Казань")

    def test_old_vacancy_is_visible_and_list_query_count_is_constant(self):
        old = create_vacancy(
            role="Old",
            datetime_created=timezone.now() - timedelta(days=120),
        )
        skill = create_skill(name="Analytics")
        old.required_skills.create(skill=skill)

        def query_count(count):
            for index in range(count):
                vacancy = create_vacancy(role=f"Vacancy {count}-{index}")
                vacancy.required_skills.create(
                    skill=create_skill(name=f"Skill {count}-{index}")
                )
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get("/vacancies/", {"limit": "100"})
                self.assertEqual(response.status_code, status.HTTP_200_OK)
            return len(queries)

        one_count = query_count(1)
        five_count = query_count(5)
        self.assertLessEqual(five_count, one_count)


class VacancyDetailContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_inactive_or_private_detail_is_hidden_from_outsider(self):
        outsider = create_user(prefix="outsider")
        self.client.force_authenticate(outsider)
        for vacancy in (
            create_vacancy(is_active=False),
            create_vacancy(project=create_project(is_public=False)),
            create_vacancy(project=create_project(draft=True)),
        ):
            with self.subTest(vacancy=vacancy.id):
                response = self.client.get(f"/vacancies/{vacancy.id}/")
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_leader_staff_and_superuser_can_open_inactive_detail(self):
        leader = create_user(prefix="leader")
        vacancy = create_vacancy(project=create_project(leader=leader), is_active=False)
        for user in (
            leader,
            create_user(prefix="staff", is_staff=True),
            create_user(prefix="superuser", is_superuser=True),
        ):
            with self.subTest(user=user.id):
                self.client.force_authenticate(user)
                self.assertEqual(
                    self.client.get(f"/vacancies/{vacancy.id}/").status_code,
                    status.HTTP_200_OK,
                )


class VacancyResponseContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("vacancy.response_services.send_email.delay")
    def test_request_user_is_used_and_foreign_file_is_rejected(self, send_email):
        applicant = create_user(prefix="applicant")
        other = create_user(prefix="other")
        vacancy = create_vacancy()
        foreign_file = create_user_file(user=other)
        self.client.force_authenticate(applicant)

        response = self.client.post(
            f"/vacancies/{vacancy.id}/responses/",
            {
                "user_id": other.id,
                "why_me": "Подхожу",
                "accompanying_file": foreign_file.link,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(VacancyResponse.objects.exists())
        own_file = create_user_file(user=applicant)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/vacancies/{vacancy.id}/responses/",
                {
                    "user_id": other.id,
                    "why_me": "Подхожу",
                    "accompanying_file": own_file.link,
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(VacancyResponse.objects.get().user, applicant)
        send_email.assert_called_once()

    def test_member_and_duplicate_response_are_rejected(self):
        leader = create_user(prefix="leader")
        member = create_user(prefix="member")
        project = create_project(leader=leader)
        Collaborator.objects.create(project=project, user=member, role="Developer")
        vacancy = create_vacancy(project=project)
        self.client.force_authenticate(member)
        response = self.client.post(
            f"/vacancies/{vacancy.id}/responses/", {"why_me": "Member"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        outsider = create_user(prefix="outsider")
        create_vacancy_response(user=outsider, vacancy=vacancy)
        self.client.force_authenticate(outsider)
        duplicate = self.client.post(
            f"/vacancies/{vacancy.id}/responses/", {"why_me": "Again"}, format="json"
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

    def test_response_list_requires_manager_and_never_exposes_private_profile_fields(
        self,
    ):
        leader = create_user(prefix="leader")
        applicant = create_user(prefix="applicant")
        project = create_project(leader=leader)
        vacancy = create_vacancy(project=project)
        create_vacancy_response(user=applicant, vacancy=vacancy)

        outsider = create_user(prefix="outsider")
        self.client.force_authenticate(outsider)
        self.assertEqual(
            self.client.get(f"/vacancies/{vacancy.id}/responses/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.client.force_authenticate(leader)
        response = self.client.get(f"/vacancies/{vacancy.id}/responses/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert_private_fields_absent(self, response.data)

    def test_response_detail_is_visible_only_to_owner_or_vacancy_manager(self):
        leader = create_user(prefix="leader")
        applicant = create_user(prefix="applicant")
        project = create_project(leader=leader)
        vacancy_response = create_vacancy_response(
            user=applicant,
            vacancy=create_vacancy(project=project),
        )

        self.assertEqual(
            self.client.get(f"/vacancies/responses/{vacancy_response.id}/").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.client.force_authenticate(create_user(prefix="outsider"))
        self.assertEqual(
            self.client.get(f"/vacancies/responses/{vacancy_response.id}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        for user in (applicant, leader, create_user(prefix="staff", is_staff=True)):
            with self.subTest(user=user.id):
                self.client.force_authenticate(user)
                response = self.client.get(f"/vacancies/responses/{vacancy_response.id}/")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                assert_private_fields_absent(self, response.data)

    def test_unknown_vacancy_and_response_return_not_found(self):
        user = create_user(prefix="user")
        self.client.force_authenticate(user)
        self.assertEqual(
            self.client.get("/vacancies/999999/responses/").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get("/vacancies/responses/999999/").status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_manager_response_list_query_count_is_constant(self):
        leader = create_user(prefix="leader")
        vacancy = create_vacancy(project=create_project(leader=leader))
        self.client.force_authenticate(leader)

        def query_count(count):
            for index in range(count):
                user = create_user(prefix=f"candidate-{count}-{index}")
                user.skills.create(skill=create_skill(name=f"Candidate {count}-{index}"))
                create_vacancy_response(user=user, vacancy=vacancy)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(f"/vacancies/{vacancy.id}/responses/")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
            return len(queries)

        one_count = query_count(1)
        five_count = query_count(5)
        self.assertLessEqual(five_count, one_count)

    def test_pending_owner_can_edit_replace_remove_file_and_withdraw(self):
        applicant = create_user(prefix="applicant")
        first_file = create_user_file(user=applicant)
        second_file = create_user_file(user=applicant)
        vacancy_response = create_vacancy_response(
            user=applicant,
            accompanying_file=first_file,
        )
        self.client.force_authenticate(applicant)

        updated = self.client.patch(
            f"/vacancies/responses/{vacancy_response.id}/",
            {"why_me": "Обновлено", "accompanying_file": second_file.link},
            format="json",
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data["why_me"], "Обновлено")
        removed = self.client.patch(
            f"/vacancies/responses/{vacancy_response.id}/",
            {"accompanying_file": None},
            format="json",
        )
        self.assertIsNone(removed.data["accompanying_file"])
        withdrawn = self.client.delete(f"/vacancies/responses/{vacancy_response.id}/")
        self.assertEqual(withdrawn.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(VacancyResponse.objects.filter(pk=vacancy_response.pk).exists())

    def test_processed_response_cannot_be_edited_or_withdrawn(self):
        applicant = create_user(prefix="applicant")
        vacancy_response = create_vacancy_response(user=applicant, is_approved=True)
        self.client.force_authenticate(applicant)
        self.assertEqual(
            self.client.patch(
                f"/vacancies/responses/{vacancy_response.id}/",
                {"why_me": "Changed"},
                format="json",
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.delete(
                f"/vacancies/responses/{vacancy_response.id}/"
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_self_list_requires_auth_and_contains_vacancy_project(self):
        self.assertEqual(
            self.client.get("/vacancies/responses/self").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        applicant = create_user(prefix="applicant")
        own = create_vacancy_response(user=applicant)
        create_vacancy_response()
        self.client.force_authenticate(applicant)
        response = self.client.get("/vacancies/responses/self")
        self.assertEqual(response.data["results"][0]["id"], own.id)
        self.assertEqual(
            response.data["results"][0]["vacancy"]["project"]["id"],
            own.vacancy.project_id,
        )

    def test_anonymous_user_cannot_create_response(self):
        vacancy = create_vacancy()
        response = self.client.post(
            f"/vacancies/{vacancy.id}/responses/",
            {"why_me": "Подхожу"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(VacancyResponse.objects.exists())


class VacancyDecisionContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("vacancy.response_services.send_email.delay")
    def test_accept_is_atomic_closes_vacancy_and_declines_other_pending(self, send_email):
        leader = create_user(prefix="leader")
        accepted_user = create_user(prefix="accepted")
        rejected_user = create_user(prefix="rejected")
        project = create_project(leader=leader)
        vacancy = create_vacancy(project=project, role="Designer")
        accepted = create_vacancy_response(user=accepted_user, vacancy=vacancy)
        rejected = create_vacancy_response(user=rejected_user, vacancy=vacancy)
        self.client.force_authenticate(leader)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/vacancies/responses/{accepted.id}/accept/")

        accepted.refresh_from_db()
        rejected.refresh_from_db()
        vacancy.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(accepted.is_approved)
        self.assertFalse(rejected.is_approved)
        self.assertFalse(vacancy.is_active)
        self.assertTrue(
            Collaborator.objects.filter(
                project=project,
                user=accepted_user,
                role="Designer",
            ).exists()
        )
        self.assertEqual(send_email.call_count, 2)
        self.assertTrue(
            Notification.objects.filter(
                recipient=accepted_user,
                type=Notification.Type.VACANCY_RESPONSE_ACCEPTED,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=rejected_user,
                type=Notification.Type.VACANCY_RESPONSE_DECLINED,
            ).exists()
        )
        self.assertEqual(
            self.client.post(f"/vacancies/responses/{accepted.id}/accept/").status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            Collaborator.objects.filter(
                project=project,
                user=accepted_user,
            ).count(),
            1,
        )

    def test_failed_accept_rolls_back_all_changes(self):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        vacancy = create_vacancy(project=project)
        vacancy_response = create_vacancy_response(vacancy=vacancy)
        self.client.force_authenticate(leader)

        with patch(
            "vacancy.response_services.Collaborator.objects.create",
            side_effect=RuntimeError("database error"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/vacancies/responses/{vacancy_response.id}/accept/")

        vacancy.refresh_from_db()
        vacancy_response.refresh_from_db()
        self.assertTrue(vacancy.is_active)
        self.assertIsNone(vacancy_response.is_approved)

    def test_close_reopen_and_safe_delete(self):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        vacancy = create_vacancy(project=project)
        pending = create_vacancy_response(vacancy=vacancy)
        self.client.force_authenticate(leader)

        closed = self.client.post(f"/vacancies/{vacancy.id}/close/")
        self.assertEqual(closed.status_code, status.HTTP_200_OK)
        pending.refresh_from_db()
        self.assertFalse(pending.is_approved)
        self.assertEqual(
            self.client.delete(f"/vacancies/{vacancy.id}/").status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        reopened = self.client.post(f"/vacancies/{vacancy.id}/reopen/")
        self.assertEqual(reopened.status_code, status.HTTP_200_OK)
        vacancy.refresh_from_db()
        self.assertTrue(vacancy.is_active)

        project.draft = True
        project.save(update_fields=("draft",))
        self.client.post(f"/vacancies/{vacancy.id}/close/")
        self.assertEqual(
            self.client.post(f"/vacancies/{vacancy.id}/reopen/").status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_only_manager_can_close_or_reopen_vacancy(self):
        leader = create_user(prefix="leader")
        vacancy = create_vacancy(project=create_project(leader=leader))
        outsider = create_user(prefix="outsider")
        self.client.force_authenticate(outsider)

        self.assertEqual(
            self.client.post(f"/vacancies/{vacancy.id}/close/").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(f"/vacancies/{vacancy.id}/reopen/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        for user in (
            leader,
            create_user(prefix="staff", is_staff=True),
            create_user(prefix="superuser", is_superuser=True),
        ):
            with self.subTest(user=user.id):
                self.client.force_authenticate(user)
                self.assertEqual(
                    self.client.post(f"/vacancies/{vacancy.id}/close/").status_code,
                    status.HTTP_200_OK,
                )
                self.assertEqual(
                    self.client.post(f"/vacancies/{vacancy.id}/reopen/").status_code,
                    status.HTTP_200_OK,
                )
