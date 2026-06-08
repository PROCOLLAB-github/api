from django.test import RequestFactory, TestCase

from vacancy.permissions import (
    IsProjectLeaderForVacancyResponse,
    IsVacancyProjectLeader,
    IsVacancyResponseOwnerOrReadOnly,
)
from vacancy.tests.helpers import create_project, create_user, create_vacancy_response


class VacancyPermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_vacancy_project_leader_can_write_vacancy(self):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        vacancy = project.vacancies.create(role="Backend")
        request = self.factory.patch("/vacancies/1/")
        request.user = leader

        self.assertTrue(
            IsVacancyProjectLeader().has_object_permission(request, None, vacancy)
        )

    def test_vacancy_non_leader_cannot_write_vacancy(self):
        outsider = create_user(prefix="outsider")
        vacancy = create_vacancy_response().vacancy
        request = self.factory.patch("/vacancies/1/")
        request.user = outsider

        self.assertFalse(
            IsVacancyProjectLeader().has_object_permission(request, None, vacancy)
        )

    def test_response_owner_can_write_own_response(self):
        vacancy_response = create_vacancy_response()
        request = self.factory.patch("/vacancies/responses/1/")
        request.user = vacancy_response.user

        self.assertTrue(
            IsVacancyResponseOwnerOrReadOnly().has_object_permission(
                request,
                None,
                vacancy_response,
            )
        )

    def test_project_leader_can_decide_response(self):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        vacancy_response = create_vacancy_response(
            vacancy=project.vacancies.create(role="Backend")
        )
        request = self.factory.post("/vacancies/responses/1/accept/")
        request.user = leader

        self.assertTrue(
            IsProjectLeaderForVacancyResponse().has_object_permission(
                request,
                None,
                vacancy_response,
            )
        )
