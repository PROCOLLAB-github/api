from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from partner_programs.models import PartnerProgram, PartnerProgramProject
from projects.models import Project
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from users.models import CustomUser


class DistributedEvaluationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        now = timezone.now()

        self.expert_user = CustomUser.objects.create_user(
            email="expert@example.com",
            password="pass",
            first_name="Expert",
            last_name="User",
            birthday="1990-01-01",
            user_type=CustomUser.EXPERT,
            is_active=True,
        )
        self.other_expert_user = CustomUser.objects.create_user(
            email="expert2@example.com",
            password="pass",
            first_name="Second",
            last_name="Expert",
            birthday="1991-01-01",
            user_type=CustomUser.EXPERT,
            is_active=True,
        )
        self.leader = CustomUser.objects.create_user(
            email="leader@example.com",
            password="pass",
            first_name="Leader",
            last_name="User",
            birthday="1992-01-01",
            user_type=CustomUser.MEMBER,
            is_active=True,
        )

        self.program = PartnerProgram.objects.create(
            name="Program",
            tag="program_tag",
            description="Program description",
            city="Moscow",
            data_schema={},
            draft=False,
            projects_availability="all_users",
            datetime_registration_ends=now + timezone.timedelta(days=10),
            datetime_started=now - timezone.timedelta(days=1),
            datetime_finished=now + timezone.timedelta(days=30),
            max_project_rates=2,
        )
        self.expert_user.expert.programs.add(self.program)
        self.other_expert_user.expert.programs.add(self.program)

        self.project_1 = Project.objects.create(
            leader=self.leader,
            draft=False,
            is_public=False,
            name="Project 1",
        )
        self.project_2 = Project.objects.create(
            leader=self.leader,
            draft=False,
            is_public=False,
            name="Project 2",
        )
        PartnerProgramProject.objects.create(
            partner_program=self.program,
            project=self.project_1,
        )
        PartnerProgramProject.objects.create(
            partner_program=self.program,
            project=self.project_2,
        )

        self.criteria = Criteria.objects.create(
            name="Impact",
            type="int",
            min_value=0,
            max_value=10,
            partner_program=self.program,
        )

    def _projects_url(self) -> str:
        return f"/rate-project/{self.program.id}"

    def _rate_url(self, project_id: int) -> str:
        return f"/rate-project/rate/{project_id}"

    def test_list_projects_without_distribution_returns_all_program_projects(self):
        self.client.force_authenticate(self.expert_user)

        response = self.client.get(self._projects_url())

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data["results"]}
        self.assertSetEqual(returned_ids, {self.project_1.id, self.project_2.id})

    def test_list_projects_with_distribution_returns_only_assigned_projects(self):
        self.program.is_distributed_evaluation = True
        self.program.save(update_fields=["is_distributed_evaluation"])
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=self.project_1,
            expert=self.expert_user.expert,
        )
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=self.project_2,
            expert=self.other_expert_user.expert,
        )

        self.client.force_authenticate(self.expert_user)
        response = self.client.get(self._projects_url())

        self.assertEqual(response.status_code, 200)
        returned_ids = [item["id"] for item in response.data["results"]]
        self.assertListEqual(returned_ids, [self.project_1.id])

    @patch("project_rates.views.send_email.delay")
    def test_rate_project_with_distribution_rejects_unassigned_expert(self, _mock_delay):
        self.program.is_distributed_evaluation = True
        self.program.save(update_fields=["is_distributed_evaluation"])

        self.client.force_authenticate(self.expert_user)
        response = self.client.post(
            self._rate_url(self.project_1.id),
            [{"criterion_id": self.criteria.id, "value": "8"}],
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["error"], "you are not assigned to rate this project"
        )
        self.assertFalse(ProjectScore.objects.filter(project=self.project_1).exists())

    @patch("project_rates.views.send_email.delay")
    def test_rate_project_with_distribution_accepts_assigned_expert(self, mock_delay):
        self.program.is_distributed_evaluation = True
        self.program.save(update_fields=["is_distributed_evaluation"])
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=self.project_1,
            expert=self.expert_user.expert,
        )

        self.client.force_authenticate(self.expert_user)
        response = self.client.post(
            self._rate_url(self.project_1.id),
            [{"criterion_id": self.criteria.id, "value": "8"}],
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            ProjectScore.objects.filter(
                project=self.project_1,
                user=self.expert_user,
                criteria=self.criteria,
                value="8",
            ).exists()
        )
        mock_delay.assert_called_once()


class ProjectExpertAssignmentModelTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.program = PartnerProgram.objects.create(
            name="Program",
            tag="program_tag",
            description="Program description",
            city="Moscow",
            data_schema={},
            draft=False,
            projects_availability="all_users",
            datetime_registration_ends=now + timezone.timedelta(days=10),
            datetime_started=now - timezone.timedelta(days=1),
            datetime_finished=now + timezone.timedelta(days=30),
            max_project_rates=1,
        )

        self.leader = CustomUser.objects.create_user(
            email="leader2@example.com",
            password="pass",
            first_name="Leader",
            last_name="Two",
            birthday="1993-01-01",
            user_type=CustomUser.MEMBER,
            is_active=True,
        )
        self.project = Project.objects.create(
            leader=self.leader,
            draft=False,
            is_public=False,
            name="Project",
        )
        PartnerProgramProject.objects.create(
            partner_program=self.program,
            project=self.project,
        )

        self.expert_1_user = CustomUser.objects.create_user(
            email="model-expert-1@example.com",
            password="pass",
            first_name="Model",
            last_name="Expert1",
            birthday="1990-02-01",
            user_type=CustomUser.EXPERT,
            is_active=True,
        )
        self.expert_2_user = CustomUser.objects.create_user(
            email="model-expert-2@example.com",
            password="pass",
            first_name="Model",
            last_name="Expert2",
            birthday="1990-03-01",
            user_type=CustomUser.EXPERT,
            is_active=True,
        )
        self.expert_1_user.expert.programs.add(self.program)
        self.expert_2_user.expert.programs.add(self.program)

    def test_assignment_requires_expert_in_program(self):
        self.expert_1_user.expert.programs.remove(self.program)

        with self.assertRaises(ValidationError):
            ProjectExpertAssignment.objects.create(
                partner_program=self.program,
                project=self.project,
                expert=self.expert_1_user.expert,
            )

    def test_assignment_requires_project_link_to_program(self):
        other_program = PartnerProgram.objects.create(
            name="Other Program",
            tag="other_program_tag",
            description="Program description",
            city="Moscow",
            data_schema={},
            draft=False,
            projects_availability="all_users",
            datetime_registration_ends=timezone.now() + timezone.timedelta(days=10),
            datetime_started=timezone.now() - timezone.timedelta(days=1),
            datetime_finished=timezone.now() + timezone.timedelta(days=30),
        )
        self.expert_1_user.expert.programs.add(other_program)

        with self.assertRaises(ValidationError):
            ProjectExpertAssignment.objects.create(
                partner_program=other_program,
                project=self.project,
                expert=self.expert_1_user.expert,
            )

    def test_assignment_respects_max_project_rates_limit(self):
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=self.project,
            expert=self.expert_1_user.expert,
        )

        with self.assertRaises(ValidationError):
            ProjectExpertAssignment.objects.create(
                partner_program=self.program,
                project=self.project,
                expert=self.expert_2_user.expert,
            )

    def test_assignment_cannot_be_deleted_after_scoring(self):
        assignment = ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=self.project,
            expert=self.expert_1_user.expert,
        )
        criteria = Criteria.objects.create(
            name="Impact",
            type="int",
            min_value=0,
            max_value=10,
            partner_program=self.program,
        )
        ProjectScore.objects.create(
            criteria=criteria,
            user=self.expert_1_user,
            project=self.project,
            value="7",
        )

        with self.assertRaises(ValidationError):
            assignment.delete()
