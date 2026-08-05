from datetime import date

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from projects.models import Achievement, ProjectGoal
from projects.tests.helpers import (
    create_collaborator,
    create_project,
    create_project_goal,
    create_user,
)


class ProjectWorkspaceContentAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.leader = create_user(prefix="workspace-content-leader")
        self.collaborator = create_user(prefix="workspace-content-collaborator")
        self.outsider = create_user(prefix="workspace-content-outsider")
        self.staff = create_user(prefix="workspace-content-staff")
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])
        self.project = create_project(
            leader=self.leader,
            draft=True,
            is_public=False,
        )
        create_collaborator(self.project, user=self.collaborator)

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def goals_url(self, project=None):
        project = project or self.project
        return f"/projects/{project.pk}/workspace/goals/"

    def goal_url(self, goal, project=None):
        project = project or self.project
        return f"{self.goals_url(project)}{goal.pk}/"

    def achievements_url(self, project=None):
        project = project or self.project
        return f"/projects/{project.pk}/workspace/achievements/"

    def achievement_url(self, achievement, project=None):
        project = project or self.project
        return f"{self.achievements_url(project)}{achievement.pk}/"

    def test_workspace_content_requires_authentication(self):
        self.assertEqual(self.client.get(self.goals_url()).status_code, 401)
        self.assertEqual(self.client.get(self.achievements_url()).status_code, 401)

    def test_leader_can_create_list_update_and_delete_goal(self):
        self.authenticate(self.leader)

        create_response = self.client.post(
            self.goals_url(),
            {
                "title": "  Подготовить прототип  ",
                "completion_date": "2026-12-15",
                "responsible": self.collaborator.pk,
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, 201)
        goal = ProjectGoal.objects.get(pk=create_response.data["id"])
        self.assertEqual(goal.project, self.project)
        self.assertEqual(goal.title, "Подготовить прототип")
        self.assertEqual(goal.responsible, self.collaborator)

        list_response = self.client.get(self.goals_url())
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(
            list_response.data,
            [
                {
                    "id": goal.pk,
                    "title": "Подготовить прототип",
                    "completion_date": "2026-12-15",
                    "responsible": self.collaborator.pk,
                }
            ],
        )

        update_response = self.client.patch(
            self.goal_url(goal),
            {"title": "Провести пилот", "responsible": self.leader.pk},
            format="json",
        )
        self.assertEqual(update_response.status_code, 200)
        goal.refresh_from_db()
        self.assertEqual(goal.title, "Провести пилот")
        self.assertEqual(goal.responsible, self.leader)

        delete_response = self.client.delete(self.goal_url(goal))
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(ProjectGoal.objects.filter(pk=goal.pk).exists())

    def test_collaborator_can_read_private_project_but_cannot_change_goal(self):
        goal = create_project_goal(self.project, responsible=self.collaborator)
        Achievement.objects.create(
            project=self.project,
            title="Командное достижение",
            status="2024",
        )
        self.authenticate(self.collaborator)

        self.assertEqual(self.client.get(self.goals_url()).status_code, 200)
        self.assertEqual(self.client.get(self.achievements_url()).status_code, 200)
        create_response = self.client.post(
            self.goals_url(),
            {"title": "Новая цель", "responsible": self.collaborator.pk},
            format="json",
        )
        update_response = self.client.patch(
            self.goal_url(goal),
            {"title": "Измененная цель"},
            format="json",
        )
        delete_response = self.client.delete(self.goal_url(goal))

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)

    def test_outsider_cannot_see_private_content_but_can_read_published_content(self):
        create_project_goal(self.project, responsible=self.leader)
        public_project = create_project(
            leader=self.leader,
            draft=False,
            is_public=True,
        )
        public_goal = create_project_goal(public_project, responsible=self.leader)
        self.authenticate(self.outsider)

        self.assertEqual(self.client.get(self.goals_url()).status_code, 404)
        self.assertEqual(self.client.get(self.achievements_url()).status_code, 404)
        public_response = self.client.get(self.goals_url(public_project))
        self.assertEqual(public_response.status_code, 200)
        self.assertEqual(public_response.data[0]["id"], public_goal.pk)
        public_write_response = self.client.post(
            self.goals_url(public_project),
            {"title": "Чужая цель", "responsible": self.leader.pk},
            format="json",
        )
        self.assertEqual(public_write_response.status_code, 403)

    def test_responsible_must_belong_to_current_project(self):
        other_project = create_project()
        other_collaborator = create_collaborator(other_project).user
        self.authenticate(self.leader)

        for invalid_user in (self.outsider, other_project.leader, other_collaborator):
            with self.subTest(user_id=invalid_user.pk):
                response = self.client.post(
                    self.goals_url(),
                    {"title": "Недопустимая цель", "responsible": invalid_user.pk},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("responsible", response.data)

        self.assertFalse(ProjectGoal.objects.filter(project=self.project).exists())

    def test_goal_rejects_whitespace_title(self):
        self.authenticate(self.leader)

        response = self.client.post(
            self.goals_url(),
            {"title": "   \t", "responsible": self.leader.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("title", response.data)

    def test_goal_cannot_be_changed_through_another_project_url(self):
        goal = create_project_goal(self.project, responsible=self.leader)
        other_project = create_project(leader=self.leader)
        self.authenticate(self.leader)

        patch_response = self.client.patch(
            self.goal_url(goal, other_project),
            {"title": "Чужой URL"},
            format="json",
        )
        delete_response = self.client.delete(self.goal_url(goal, other_project))

        self.assertEqual(patch_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)
        list_response = self.client.get(self.goals_url(other_project))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data, [])
        goal.refresh_from_db()
        self.assertNotEqual(goal.title, "Чужой URL")

    def test_failed_goal_update_does_not_apply_other_fields(self):
        goal = create_project_goal(
            self.project,
            responsible=self.leader,
            title="Исходная цель",
        )
        original_title = goal.title
        self.authenticate(self.leader)

        response = self.client.patch(
            self.goal_url(goal),
            {"title": "Не сохранять", "responsible": self.outsider.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        goal.refresh_from_db()
        self.assertEqual(goal.title, original_title)
        self.assertEqual(goal.responsible, self.leader)

    def test_staff_retains_administrative_write_access(self):
        self.authenticate(self.staff)

        goal_response = self.client.post(
            self.goals_url(),
            {"title": "Административная цель", "responsible": self.leader.pk},
            format="json",
        )
        achievement_response = self.client.post(
            self.achievements_url(),
            {"title": "Административное достижение", "year": 2020},
            format="json",
        )

        self.assertEqual(goal_response.status_code, 201)
        self.assertEqual(achievement_response.status_code, 201)

    def test_achievement_full_crud_maps_year_to_legacy_status(self):
        self.authenticate(self.leader)

        create_response = self.client.post(
            self.achievements_url(),
            {"title": "  Победа в конкурсе  ", "year": 2024},
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.data["year"], 2024)
        achievement = Achievement.objects.get(pk=create_response.data["id"])
        self.assertEqual(achievement.project, self.project)
        self.assertEqual(achievement.title, "Победа в конкурсе")
        self.assertEqual(achievement.status, "2024")

        list_response = self.client.get(self.achievements_url())
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data[0]["year"], 2024)

        update_response = self.client.patch(
            self.achievement_url(achievement),
            {"title": "Финал конкурса", "year": 2025},
            format="json",
        )
        self.assertEqual(update_response.status_code, 200)
        achievement.refresh_from_db()
        self.assertEqual(achievement.title, "Финал конкурса")
        self.assertEqual(achievement.status, "2025")

        delete_response = self.client.delete(self.achievement_url(achievement))
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(Achievement.objects.filter(pk=achievement.pk).exists())

    def test_achievement_rejects_invalid_year_and_whitespace_title(self):
        self.authenticate(self.leader)

        payloads = (
            {"title": "Слишком рано", "year": 1999},
            {"title": "Слишком поздно", "year": date.today().year + 1},
            {"title": "   ", "year": 2024},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.client.post(
                    self.achievements_url(),
                    payload,
                    format="json",
                )
                self.assertEqual(response.status_code, 400)

        self.assertFalse(Achievement.objects.filter(project=self.project).exists())

    def test_achievement_cannot_be_changed_through_another_project_url(self):
        achievement = Achievement.objects.create(
            project=self.project,
            title="Достижение",
            status="2024",
        )
        other_project = create_project(leader=self.leader)
        self.authenticate(self.leader)

        response = self.client.patch(
            self.achievement_url(achievement, other_project),
            {"year": 2025},
            format="json",
        )
        delete_response = self.client.delete(
            self.achievement_url(achievement, other_project)
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)
        achievement.refresh_from_db()
        self.assertEqual(achievement.status, "2024")

    def test_failed_achievement_update_is_atomic(self):
        achievement = Achievement.objects.create(
            project=self.project,
            title="Исходное достижение",
            status="2024",
        )
        self.authenticate(self.leader)

        response = self.client.patch(
            self.achievement_url(achievement),
            {"title": "Не сохранять", "year": 1999},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        achievement.refresh_from_db()
        self.assertEqual(achievement.title, "Исходное достижение")
        self.assertEqual(achievement.status, "2024")

    def test_workspace_lists_do_not_create_n_plus_one_queries(self):
        for index in range(5):
            participant = create_user(prefix=f"goal-responsible-{index}")
            create_collaborator(self.project, user=participant)
            create_project_goal(self.project, responsible=participant)
            Achievement.objects.create(
                project=self.project,
                title=f"Достижение {index}",
                status=str(2020 + index),
            )
        self.authenticate(self.leader)

        with CaptureQueriesContext(connection) as goal_queries:
            goal_response = self.client.get(self.goals_url())
        with CaptureQueriesContext(connection) as achievement_queries:
            achievement_response = self.client.get(self.achievements_url())

        self.assertEqual(goal_response.status_code, 200)
        self.assertEqual(achievement_response.status_code, 200)
        self.assertEqual(len(goal_response.data), 5)
        self.assertEqual(len(achievement_response.data), 5)
        self.assertLessEqual(len(goal_queries), 3)
        self.assertLessEqual(len(achievement_queries), 3)

    def test_legacy_and_workspace_project_endpoints_remain_available(self):
        goal = create_project_goal(self.project, responsible=self.leader)
        self.authenticate(self.leader)

        legacy_response = self.client.get(f"/projects/{self.project.pk}/goals/")
        legacy_achievements_response = self.client.get("/projects/achievements/")
        workspace_response = self.client.get(f"/projects/{self.project.pk}/workspace/")

        self.assertEqual(legacy_response.status_code, 200)
        self.assertEqual(legacy_response.data[0]["id"], goal.pk)
        self.assertEqual(legacy_achievements_response.status_code, 200)
        self.assertEqual(workspace_response.status_code, 200)
        self.assertEqual(workspace_response.data["id"], self.project.pk)
