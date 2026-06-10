from django.test import TestCase
from rest_framework.test import APIClient

from projects.models import ProjectGoal

from .helpers import (
    create_project_context,
    create_project_goal,
    create_user,
)


class ProjectGoalRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        context = create_project_context(
            user_prefix="project-goal-leader",
            draft=True,
        )
        self.user = context.user
        self.project = context.project
        self.client.force_authenticate(self.user)

    def test_leader_can_create_goals_list(self):
        response = self.client.post(
            f"/projects/{self.project.id}/goals/",
            [
                {
                    "title": "Prepare prototype",
                    "responsible": self.user.id,
                },
                {
                    "title": "Run pilot",
                    "responsible": self.user.id,
                },
            ],
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(ProjectGoal.objects.filter(project=self.project).count(), 2)
        self.assertEqual(
            list(
                ProjectGoal.objects.filter(project=self.project)
                .order_by("title")
                .values_list("title", flat=True)
            ),
            [
                "Prepare prototype",
                "Run pilot",
            ],
        )

    def test_leader_can_partially_update_single_goal(self):
        goal = create_project_goal(
            self.project,
            responsible=self.user,
            title="Prepare prototype",
        )

        response = self.client.patch(
            f"/projects/{self.project.id}/goals/{goal.id}/",
            {
                "is_done": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        goal.refresh_from_db()
        self.assertTrue(goal.is_done)
        self.assertEqual(goal.project, self.project)

    def test_non_leader_cannot_create_project_goals(self):
        non_leader = create_user(prefix="project-goal-non-leader")
        self.client.force_authenticate(non_leader)

        response = self.client.post(
            f"/projects/{self.project.id}/goals/",
            [
                {
                    "title": "Prepare prototype",
                    "responsible": non_leader.id,
                },
            ],
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ProjectGoal.objects.filter(project=self.project).exists())
