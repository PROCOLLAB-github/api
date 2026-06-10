from django.test import TestCase
from rest_framework.test import APIClient

from users.models import LikesOnProject

from .helpers import (
    add_user_to_program,
    attach_skill,
    build_partner_program,
    build_project,
    build_skill,
    build_user,
)


class PublicUserListAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_public_users_can_be_filtered_by_fullname(self):
        matched_user = build_user(
            email="matched@example.com",
            first_name="Алексей",
            last_name="Петров",
        )
        build_user(
            email="not-matched@example.com",
            first_name="Иван",
            last_name="Сидоров",
        )

        response = self.client.get("/auth/public-users/?fullname=Алексей Петров")

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(returned_ids, {matched_user.id})

    def test_public_users_can_be_filtered_by_skill(self):
        matched_user = build_user(email="skilled@example.com")
        other_user = build_user(email="unskilled@example.com")
        skill = build_skill("Django")
        attach_skill(matched_user, skill)

        response = self.client.get("/auth/public-users/?skills__contains=Django")

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data["results"]}
        self.assertIn(matched_user.id, returned_ids)
        self.assertNotIn(other_user.id, returned_ids)

    def test_public_users_can_be_filtered_by_partner_program(self):
        matched_user = build_user(email="program-user@example.com")
        other_user = build_user(email="not-program-user@example.com")
        program = build_partner_program()
        add_user_to_program(matched_user, program)

        response = self.client.get(f"/auth/public-users/?partner_program={program.id}")

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data["results"]}
        self.assertIn(matched_user.id, returned_ids)
        self.assertNotIn(other_user.id, returned_ids)


class UserProjectsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = build_user(email="projects-user@example.com")
        self.client.force_authenticate(user=self.user)

    def test_user_projects_returns_leader_and_collaborator_projects(self):
        leader_project = build_project(self.user, name="Leader project")
        collaborator_leader = build_user(email="collaborator-leader@example.com")
        collaborator_project = build_project(
            collaborator_leader,
            name="Collaborator project",
        )
        collaborator_project.collaborator_set.create(user=self.user, role="Member")

        response = self.client.get("/auth/users/projects/")

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data["results"]}
        self.assertSetEqual(returned_ids, {leader_project.id, collaborator_project.id})

    def test_user_leader_projects_returns_only_owned_projects(self):
        leader_project = build_project(self.user, name="Leader project")
        other_leader = build_user(email="other-leader@example.com")
        other_project = build_project(other_leader, name="Other project")
        other_project.collaborator_set.create(user=self.user, role="Member")

        response = self.client.get("/auth/users/projects/leader/")

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data["results"]}
        self.assertSetEqual(returned_ids, {leader_project.id})

    def test_liked_projects_returns_only_active_likes(self):
        liked_project = build_project(self.user, name="Liked project")
        unliked_project = build_project(self.user, name="Unliked project")
        LikesOnProject.objects.create(user=self.user, project=liked_project)
        LikesOnProject.objects.create(
            user=self.user,
            project=unliked_project,
            is_liked=False,
        )

        response = self.client.get("/auth/users/liked/")

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data}
        self.assertIn(liked_project.id, returned_ids)
        self.assertNotIn(unliked_project.id, returned_ids)
