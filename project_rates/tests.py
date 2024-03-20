from datetime import datetime
from unittest import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from industries.models import Industry
from partner_programs.models import PartnerProgram
from project_rates.models import Criteria, ProjectScore, User
from project_rates.views import RateProjects, RateProject, RateProjectsDetails
from projects.models import Project
from tests.constants import USER_CREATE_DATA
from users.models import Expert, CustomUser
from users.views import UserList


class ProjectRateTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.project_rate_list_view = RateProjects.as_view()
        self.project_rate_detail_view = RateProjectsDetails.as_view()
        self.project_rate_create_view = RateProject.as_view()
        self.user_list_view = UserList.as_view()

        self.program = PartnerProgram.objects.create(
            name="Название программы",
            tag="Тег программы",
            description="Описание программы",
            city="Город",
            data_schema={
                "field1": "type1",
                "field2": "type2"
            },
            datetime_registration_ends=datetime.now(),
            datetime_started=datetime.now(),
            datetime_finished=datetime.now(),
            datetime_created=datetime.now(),
            datetime_updated=datetime.now(),
        )

        self.criteria_numeric = Criteria.objects.create(
            name="Тестовое качество",
            type="int",
            min_value=0,
            max_value=100,
            partner_program=self.program
        )

        self.criteria_comment = Criteria.objects.create(
            name="Комментарий",
            type="str",
            partner_program=self.program
        )

        self.user = None
        self.project = None

        self.project_rate_create_data = [
            {
                "criterion_id": self.criteria_numeric.id,
                "value": 1
            },
            {
                "criterion_id": self.criteria_comment.id,
                "value": "Тестовые слова"
            },
        ]

    def test_successful_project_rates_creation(self):
        self.create_user_project()
        request = self.factory.post(f"rate-project/rate/{self.project.id}", self.project_rate_create_data, format="json")
        force_authenticate(request, user=self.user)

        response = self.project_rate_create_view(request, project_id=self.project.id)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['success'], True)

    # def test_successful_project_rates_list_should_succeed(self):
    #     self.create_user_project()
    #     ProjectScore.objects.bulk_create([
    #         ProjectScore(criteria=self.criteria_numeric, user=self.user, project=self.project, value=1),
    #         ProjectScore(criteria=self.criteria_comment, user=self.user, project=self.project, value="Test text")
    #     ])
    #     request = self.factory.get(f"rate-project/{self.criteria_numeric.partner_program.id}")
    #     force_authenticate(request, user=self.user)
    #
    #     response = self.project_rate_list_view(request, program_id=self.criteria_numeric.partner_program.id)
    #     raise ValueError(f"{response.data}, self.")
    #     self.assertEqual(response.status_code, 200)


    def user_create(self):
        USER_CREATE_DATA['user_type'] = 3
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user

    def create_user_project(self):
        try:
            self.user = self.user_create()
        except KeyError:
            self.user = CustomUser.objects.get(email="only_for_test@test.test")
        self.expert = Expert.objects.get(user=self.user)
        self.expert.programs.add(self.program)

        self.project = Project.objects.create(
            name="Test project",
            description="Test desc",
            industry=Industry.objects.create(name="Test"),
            leader=self.user,
            step=1
        )