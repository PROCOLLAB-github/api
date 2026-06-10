from django.core.exceptions import ValidationError
from django.test import TestCase

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
