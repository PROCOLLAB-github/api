from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Specialization, SpecializationCategory
from projects.models import Collaborator
from vacancy.models import VacancyResponse
from vacancy.tests.helpers import (
    create_project,
    create_skill,
    create_user,
    create_user_file,
    create_vacancy,
    create_vacancy_response,
)


PRIVATE_FIELDS = {
    "email",
    "phone",
    "phone_number",
    "birthday",
    "password",
    "is_staff",
    "is_superuser",
    "onboarding_stage",
}


def assert_private_fields_absent(test_case: TestCase, value) -> None:
    if isinstance(value, dict):
        test_case.assertTrue(PRIVATE_FIELDS.isdisjoint(value.keys()))
        for nested in value.values():
            assert_private_fields_absent(test_case, nested)
    elif isinstance(value, list):
        for nested in value:
            assert_private_fields_absent(test_case, nested)


def make_staff(*, superuser: bool = False):
    user = create_user(prefix="superuser" if superuser else "staff")
    user.is_staff = True
    user.is_superuser = superuser
    user.save(update_fields=("is_staff", "is_superuser"))
    return user


class VacancyResponseCreateContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("vacancy.response_services.send_email.delay")
    def test_request_user_is_used_and_own_file_is_accepted(self, send_email):
        applicant = create_user(prefix="applicant")
        payload_user = create_user(prefix="payload-user")
        vacancy = create_vacancy()
        own_file = create_user_file(user=applicant)
        self.client.force_authenticate(applicant)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/vacancies/{vacancy.id}/responses/",
                {
                    "user": payload_user.id,
                    "user_id": payload_user.id,
                    "vacancy": 999999,
                    "why_me": "Подхожу",
                    "accompanying_file": own_file.link,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = VacancyResponse.objects.get()
        self.assertEqual(created.user, applicant)
        self.assertEqual(created.vacancy, vacancy)
        self.assertEqual(created.accompanying_file, own_file)
        send_email.assert_called_once()

    def test_anonymous_cannot_create_response(self):
        vacancy = create_vacancy()

        response = self.client.post(
            f"/vacancies/{vacancy.id}/responses/",
            {"why_me": "Подхожу"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(VacancyResponse.objects.exists())

    def test_leader_and_collaborator_cannot_respond_but_outsider_can(self):
        leader = create_user(prefix="leader")
        collaborator = create_user(prefix="collaborator")
        outsider = create_user(prefix="outsider")
        project = create_project(leader=leader)
        Collaborator.objects.create(
            project=project,
            user=collaborator,
            role="Developer",
        )
        vacancy = create_vacancy(project=project)

        for blocked_user in (leader, collaborator):
            with self.subTest(user=blocked_user.id):
                self.client.force_authenticate(blocked_user)
                response = self.client.post(
                    f"/vacancies/{vacancy.id}/responses/",
                    {"why_me": "Нельзя"},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.client.force_authenticate(outsider)
        response = self.client.post(
            f"/vacancies/{vacancy.id}/responses/",
            {"why_me": "Можно"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(VacancyResponse.objects.get().user, outsider)

    def test_duplicate_response_is_rejected_without_new_row(self):
        applicant = create_user(prefix="applicant")
        vacancy = create_vacancy()
        original = create_vacancy_response(user=applicant, vacancy=vacancy)
        self.client.force_authenticate(applicant)

        response = self.client.post(
            f"/vacancies/{vacancy.id}/responses/",
            {"why_me": "Повтор"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            list(VacancyResponse.objects.values_list("id", flat=True)), [original.id]
        )

    def test_unavailable_vacancy_is_rejected(self):
        applicant = create_user(prefix="applicant")
        self.client.force_authenticate(applicant)
        scenarios = (
            create_vacancy(is_active=False),
            create_vacancy(project=create_project(draft=True), is_active=True),
            create_vacancy(project=create_project(is_public=False), is_active=True),
        )

        for vacancy in scenarios:
            with self.subTest(vacancy=vacancy.id):
                response = self.client.post(
                    f"/vacancies/{vacancy.id}/responses/",
                    {"why_me": "Подхожу"},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(VacancyResponse.objects.exists())

    def test_foreign_file_is_rejected_without_disclosure(self):
        applicant = create_user(prefix="applicant")
        foreign_file = create_user_file(user=create_user(prefix="file-owner"))
        vacancy = create_vacancy()
        self.client.force_authenticate(applicant)

        response = self.client.post(
            f"/vacancies/{vacancy.id}/responses/",
            {"accompanying_file": foreign_file.link},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["accompanying_file"],
            ["Можно прикрепить только собственный файл."],
        )
        self.assertNotIn("user", response.data)
        self.assertFalse(VacancyResponse.objects.exists())


class VacancyResponseManagerContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.leader = create_user(prefix="leader")
        self.project = create_project(leader=self.leader)
        self.vacancy = create_vacancy(project=self.project)
        self.applicant = create_user(prefix="applicant")
        specialization_category = SpecializationCategory.objects.create(name="Design")
        self.specialization = Specialization.objects.create(
            name="UX designer",
            category=specialization_category,
        )
        self.applicant.v2_speciality = self.specialization
        self.applicant.save(update_fields=("v2_speciality",))
        self.response = create_vacancy_response(
            user=self.applicant,
            vacancy=self.vacancy,
            accompanying_file=create_user_file(user=self.applicant),
        )

    def test_vacancy_response_list_requires_authentication(self):
        response = self.client.get(f"/vacancies/{self.vacancy.id}/responses/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_vacancy_response_list_requires_manager(self):
        collaborator = create_user(prefix="collaborator")
        Collaborator.objects.create(
            project=self.project,
            user=collaborator,
            role="Developer",
        )
        outsider = create_user(prefix="outsider")

        for blocked_user in (outsider, collaborator):
            with self.subTest(user=blocked_user.id):
                self.client.force_authenticate(blocked_user)
                response = self.client.get(f"/vacancies/{self.vacancy.id}/responses/")
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        for manager in (self.leader, make_staff(), make_staff(superuser=True)):
            with self.subTest(manager=manager.id):
                self.client.force_authenticate(manager)
                response = self.client.get(f"/vacancies/{self.vacancy.id}/responses/")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data[0]["id"], self.response.id)

    def test_manager_contract_contains_required_fields_and_no_private_data(self):
        self.client.force_authenticate(self.leader)

        response = self.client.get(f"/vacancies/{self.vacancy.id}/responses/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data[0]
        self.assertEqual(
            set(item),
            {
                "id",
                "user",
                "why_me",
                "accompanying_file",
                "is_approved",
                "vacancy",
                "datetime_created",
                "datetime_updated",
            },
        )
        self.assertEqual(item["vacancy"], self.vacancy.id)
        self.assertEqual(item["accompanying_file"]["name"], "cv")
        self.assertEqual(item["user"]["specialization"]["id"], self.specialization.id)
        self.assertEqual(
            item["user"]["specialization"]["category"]["name"],
            "Design",
        )
        assert_private_fields_absent(self, response.data)

    def test_legacy_project_response_list_requires_manager(self):
        collaborator = create_user(prefix="collaborator")
        Collaborator.objects.create(
            project=self.project,
            user=collaborator,
            role="Developer",
        )
        outsider = create_user(prefix="outsider")

        for blocked_user in (outsider, collaborator):
            with self.subTest(user=blocked_user.id):
                self.client.force_authenticate(blocked_user)
                response = self.client.get(f"/projects/{self.project.id}/responses/")
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        for manager in (self.leader, make_staff(), make_staff(superuser=True)):
            with self.subTest(manager=manager.id):
                self.client.force_authenticate(manager)
                response = self.client.get(f"/projects/{self.project.id}/responses/")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data[0]["id"], self.response.id)
                assert_private_fields_absent(self, response.data)

    def test_manager_response_query_count_is_constant(self):
        def query_count(candidate_count):
            vacancy = create_vacancy(
                project=create_project(leader=self.leader),
                role=f"Role {candidate_count}",
            )
            for index in range(candidate_count):
                candidate = create_user(prefix=f"candidate-{candidate_count}-{index}")
                candidate.skills.create(skill=create_skill(name=f"Skill {index}"))
                create_vacancy_response(user=candidate, vacancy=vacancy)
            self.client.force_authenticate(self.leader)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(f"/vacancies/{vacancy.id}/responses/")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
            return len(queries)

        self.assertEqual(query_count(1), query_count(5))


class VacancyApplicantStateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.leader = create_user(prefix="leader")
        self.project = create_project(leader=self.leader)
        self.vacancy = create_vacancy(project=self.project)

    def get_detail(self, user=None, vacancy=None):
        self.client.force_authenticate(user=user)
        return self.client.get(f"/vacancies/{(vacancy or self.vacancy).id}/")

    def test_outsider_state_changes_after_response(self):
        outsider = create_user(prefix="outsider")

        before = self.get_detail(outsider)
        self.assertEqual(before.status_code, status.HTTP_200_OK)
        self.assertFalse(before.data["has_responded"])
        self.assertIsNone(before.data["response_status"])
        self.assertTrue(before.data["can_respond"])
        self.assertFalse(before.data["can_manage_responses"])

        create_vacancy_response(user=outsider, vacancy=self.vacancy)
        after = self.get_detail(outsider)
        self.assertTrue(after.data["has_responded"])
        self.assertEqual(after.data["response_status"], "pending")
        self.assertFalse(after.data["can_respond"])

    def test_response_status_maps_processed_responses(self):
        for is_approved, expected_status in (
            (True, "accepted"),
            (False, "rejected"),
        ):
            with self.subTest(is_approved=is_approved):
                applicant = create_user(prefix=f"applicant-{expected_status}")
                create_vacancy_response(
                    user=applicant,
                    vacancy=self.vacancy,
                    is_approved=is_approved,
                )

                response = self.get_detail(applicant)

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertTrue(response.data["has_responded"])
                self.assertEqual(response.data["response_status"], expected_status)
                self.assertFalse(response.data["can_respond"])

    def test_leader_and_collaborator_states(self):
        leader_response = self.get_detail(self.leader)
        self.assertFalse(leader_response.data["has_responded"])
        self.assertIsNone(leader_response.data["response_status"])
        self.assertFalse(leader_response.data["can_respond"])
        self.assertTrue(leader_response.data["can_manage_responses"])

        collaborator = create_user(prefix="collaborator")
        Collaborator.objects.create(
            project=self.project,
            user=collaborator,
            role="Developer",
        )
        collaborator_response = self.get_detail(collaborator)
        self.assertFalse(collaborator_response.data["can_respond"])
        self.assertFalse(collaborator_response.data["can_manage_responses"])

    def test_closed_and_anonymous_states(self):
        outsider = create_user(prefix="outsider")
        closed = create_vacancy(is_active=False)
        closed_response = self.get_detail(outsider, closed)
        self.assertFalse(closed_response.data["can_respond"])

        anonymous_response = self.get_detail(None)
        self.assertFalse(anonymous_response.data["has_responded"])
        self.assertIsNone(anonymous_response.data["response_status"])
        self.assertFalse(anonymous_response.data["can_respond"])
        self.assertFalse(anonymous_response.data["can_manage_responses"])

    def test_response_status_does_not_add_separate_detail_query(self):
        applicant = create_user(prefix="query-count-applicant")
        create_vacancy_response(user=applicant, vacancy=self.vacancy)
        self.client.force_authenticate(applicant)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(f"/vacancies/{self.vacancy.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_table = VacancyResponse._meta.db_table
        response_queries = [
            query["sql"]
            for query in queries.captured_queries
            if response_table in query["sql"]
        ]
        self.assertEqual(len(response_queries), 2)
        self.assertEqual(
            sum(
                'AS "current_user_response_is_approved"' in query
                for query in response_queries
            ),
            1,
        )
        self.assertEqual(response.data["response_status"], "pending")


class VacancyCatalogApplicantStateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.leader = create_user(prefix="catalog-leader")
        self.project = create_project(leader=self.leader)
        self.vacancy = create_vacancy(project=self.project)

    def get_catalog_item(self, user=None, vacancy=None):
        self.client.force_authenticate(user=user)
        response = self.client.get("/vacancies/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        vacancy_id = (vacancy or self.vacancy).id
        return next(item for item in response.data["results"] if item["id"] == vacancy_id)

    def test_anonymous_and_outsider_states(self):
        anonymous = self.get_catalog_item()
        self.assertFalse(anonymous["has_responded"])
        self.assertIsNone(anonymous["response_status"])
        self.assertFalse(anonymous["can_respond"])
        self.assertFalse(anonymous["can_manage_responses"])

        outsider = create_user(prefix="catalog-outsider")
        available = self.get_catalog_item(outsider)
        self.assertFalse(available["has_responded"])
        self.assertIsNone(available["response_status"])
        self.assertTrue(available["can_respond"])
        self.assertFalse(available["can_manage_responses"])

    def test_leader_and_collaborator_states(self):
        managed = self.get_catalog_item(self.leader)
        self.assertFalse(managed["has_responded"])
        self.assertFalse(managed["can_respond"])
        self.assertTrue(managed["can_manage_responses"])

        collaborator = create_user(prefix="catalog-collaborator")
        Collaborator.objects.create(
            project=self.project,
            user=collaborator,
            role="Developer",
        )
        member = self.get_catalog_item(collaborator)
        self.assertFalse(member["has_responded"])
        self.assertFalse(member["can_respond"])
        self.assertFalse(member["can_manage_responses"])

    def test_pending_response_state(self):
        applicant = create_user(prefix="catalog-pending")
        create_vacancy_response(user=applicant, vacancy=self.vacancy)

        item = self.get_catalog_item(applicant)

        self.assertTrue(item["has_responded"])
        self.assertEqual(item["response_status"], "pending")
        self.assertFalse(item["can_respond"])
        self.assertFalse(item["can_manage_responses"])

    def test_processed_response_status_mapping(self):
        for is_approved, expected_status in (
            (True, "accepted"),
            (False, "rejected"),
        ):
            with self.subTest(expected_status=expected_status):
                applicant = create_user(prefix=f"catalog-{expected_status}")
                create_vacancy_response(
                    user=applicant,
                    vacancy=self.vacancy,
                    is_approved=is_approved,
                )

                item = self.get_catalog_item(applicant)

                self.assertTrue(item["has_responded"])
                self.assertEqual(item["response_status"], expected_status)
                self.assertFalse(item["can_respond"])

    def test_catalog_query_count_does_not_grow_with_result_count(self):
        outsider = create_user(prefix="catalog-query-count")
        for index in range(4):
            create_vacancy(project=self.project, role=f"Vacancy {index}")
        self.client.force_authenticate(outsider)
        self.client.get("/vacancies/", {"limit": 5})

        def query_count(limit):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get("/vacancies/", {"limit": limit})
                self.assertEqual(response.status_code, status.HTTP_200_OK)
            return len(queries)

        self.assertEqual(query_count(1), query_count(5))


class VacancyResponseDecisionContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("vacancy.response_services.send_email.delay")
    def test_accept_closes_vacancy_adds_collaborator_and_declines_others(
        self,
        send_email,
    ):
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
        self.assertEqual(
            Collaborator.objects.filter(project=project, user=accepted_user).count(),
            1,
        )
        self.assertEqual(send_email.call_count, 2)

        repeated = self.client.post(f"/vacancies/responses/{accepted.id}/accept/")
        self.assertEqual(repeated.status_code, status.HTTP_400_BAD_REQUEST)

    def test_outsider_cannot_accept_or_decline(self):
        vacancy_response = create_vacancy_response()
        self.client.force_authenticate(create_user(prefix="outsider"))

        for action in ("accept", "decline"):
            with self.subTest(action=action):
                response = self.client.post(
                    f"/vacancies/responses/{vacancy_response.id}/{action}/"
                )
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        vacancy_response.refresh_from_db()
        self.assertIsNone(vacancy_response.is_approved)

    def test_staff_and_superuser_can_resolve_response(self):
        scenarios = (
            (make_staff(), "accept", True),
            (make_staff(superuser=True), "decline", False),
        )

        for manager, action, expected_status in scenarios:
            with self.subTest(action=action):
                vacancy_response = create_vacancy_response()
                self.client.force_authenticate(manager)

                response = self.client.post(
                    f"/vacancies/responses/{vacancy_response.id}/{action}/"
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                vacancy_response.refresh_from_db()
                self.assertEqual(vacancy_response.is_approved, expected_status)

    def test_processed_response_cannot_be_processed_again(self):
        leader = create_user(prefix="leader")
        vacancy = create_vacancy(project=create_project(leader=leader))
        vacancy_response = create_vacancy_response(vacancy=vacancy)
        self.client.force_authenticate(leader)

        declined = self.client.post(
            f"/vacancies/responses/{vacancy_response.id}/decline/"
        )
        self.assertEqual(declined.status_code, status.HTTP_200_OK)
        for action in ("accept", "decline"):
            response = self.client.post(
                f"/vacancies/responses/{vacancy_response.id}/{action}/"
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_accept_rolls_back_if_collaborator_creation_fails(self):
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


class VacancyResponseSelfContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_self_endpoint_requires_auth_and_returns_only_own_safe_data(self):
        self.assertEqual(
            self.client.get("/vacancies/responses/self").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        applicant = create_user(prefix="applicant")
        own = create_vacancy_response(user=applicant)
        create_vacancy_response()
        self.client.force_authenticate(applicant)

        response = self.client.get("/vacancies/responses/self")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data["results"]], [own.id])
        self.assertNotIn("user", response.data["results"][0])
        self.assertEqual(
            response.data["results"][0]["vacancy"]["project"]["id"],
            own.vacancy.project_id,
        )
        assert_private_fields_absent(self, response.data)
