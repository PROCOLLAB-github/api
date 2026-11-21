from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from partner_programs.tests.helpers import create_user
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import (
    create_rate_expert,
    create_rate_program,
    create_rate_project,
    create_rate_user,
    link_project_to_program,
)


class ProjectExpertAssignmentModelTests(TestCase):
    def setUp(self):
        self.program = create_rate_program(max_project_rates=1)
        self.leader = create_rate_user(prefix="assignment-leader")
        self.project = create_rate_project(
            leader=self.leader,
            name="Assignment Project",
        )
        link_project_to_program(self.program, self.project)

        self.expert_1_user = create_rate_expert(prefix="assignment-expert-1")
        self.expert_2_user = create_rate_expert(prefix="assignment-expert-2")
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
        other_program = create_rate_program(name="Other Assignment Program")
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


class ProjectExpertAssignmentAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(
            create_user(is_staff=True, is_superuser=True, is_active=True)
        )
        self.program = create_rate_program()
        self.project = create_rate_project()
        link_project_to_program(self.program, self.project)
        self.expert = create_rate_expert(program=self.program).expert
        self.assignment = ProjectExpertAssignment.objects.create(
            partner_program=self.program, project=self.project, expert=self.expert
        )
        self.url = reverse(
            "admin:project_rates_projectexpertassignment_change",
            args=[self.assignment.pk],
        )
        self.payload = {
            "partner_program": self.program.pk,
            "project": self.project.pk,
            "expert": self.expert.pk,
        }

    def test_scored_assignment_cannot_change_program_project_or_expert(self):
        other_program = create_rate_program()
        other_project = create_rate_project()
        link_project_to_program(self.program, other_project)
        link_project_to_program(other_program, self.project)
        other_expert = create_rate_expert(program=self.program).expert
        self.expert.programs.add(other_program)

        criterion = Criteria.objects.create(
            name="Impact",
            type="int",
            min_value=0,
            max_value=10,
            partner_program=self.program,
        )
        score = ProjectScore.objects.create(
            criteria=criterion, user=self.expert.user, project=self.project, value="7"
        )
        for name, replacement in {
            "partner_program": other_program.pk,
            "project": other_project.pk,
            "expert": other_expert.pk,
        }.items():
            with self.subTest(field=name):
                response = self.client.post(self.url, {**self.payload, name: replacement})
                self.assertContains(
                    response, "Нельзя снять эксперта с сохраненной оценкой."
                )
                self.assignment.refresh_from_db()
                self.assertEqual(self.assignment.partner_program_id, self.program.pk)
                self.assertEqual(self.assignment.project_id, self.project.pk)
                self.assertEqual(self.assignment.expert_id, self.expert.pk)
                self.assertTrue(self.assignment.has_scores())
                score.refresh_from_db()
                self.assertEqual(score.value, "7")

    def test_unscored_assignment_can_change_expert(self):
        expert = create_rate_expert(program=self.program).expert
        response = self.client.post(self.url, {**self.payload, "expert": expert.pk})
        self.assertEqual(response.status_code, 302)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.expert_id, expert.pk)
