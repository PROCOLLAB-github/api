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

    def test_fullname_matches_case_spacing_and_both_parts(self):
        """Регистр и пробелы не меняют выдачу; одно совпавшее слово недостаточно."""
        wanted = build_user(
            email="fullname1@example.test", first_name="Иван", last_name="Иванов"
        )
        build_user(email="fullname2@example.test", first_name="Иван", last_name="Петров")
        build_user(email="fullname3@example.test", first_name="Пётр", last_name="Иванов")
        for query in (
            "Иван Иванов",
            "иван иванов",
            "ИВАН ИВАНОВ",
            "иВаН иВаНоВ",
            "  Иван   Иванов  ",
            "Иванов Иван",
            "ив иванов",
        ):
            with self.subTest(query=query):
                response = self.client.get("/auth/public-users/", {"fullname": query})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], 1)
                self.assertEqual([u["id"] for u in response.data["results"]], [wanted.id])

    def test_all_query_parts_are_required(self):
        """Несовпавшая часть запроса исключает одноимённых пользователей целиком."""
        build_user(email="partial1@example.test", first_name="Иван", last_name="Иванов")
        build_user(email="partial2@example.test", first_name="Иван", last_name="Петров")
        for query in ("Иван НесуществующаяФамилия", "НесуществующаяФамилия Иван"):
            with self.subTest(query=query):
                response = self.client.get("/auth/public-users/", {"fullname": query})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], 0)

    def test_regex_metacharacters_match_only_literal_name(self):
        """Скобки и точки допустимы как текст, но не выполняются как regex."""
        wanted = build_user(
            email="literal@example.test", first_name="A[bc].*", last_name="Smith"
        )
        build_user(email="regex@example.test", first_name="Abbb", last_name="Smith")
        response = self.client.get("/auth/public-users/", {"fullname": "a[bc].* SMITH"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([u["id"] for u in response.data["results"]], [wanted.id])

    def test_compound_names_and_query_longer_than_model_fields(self):
        """Составные имена сохраняются; заведомо слишком длинный ввод безопасно пуст."""
        wanted = build_user(
            email="compound@example.test", first_name="Анна Мария", last_name="Ван Дейк"
        )
        for query in ("анна мария ван дейк", "ВАН ДЕЙК АННА МАРИЯ"):
            response = self.client.get("/auth/public-users/", {"fullname": query})
            self.assertEqual([u["id"] for u in response.data["results"]], [wanted.id])
        response = self.client.get("/auth/public-users/", {"fullname": "Я " * 600})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)

    def test_single_name_surname_and_literal_characters(self):
        """Одиночный фрагмент ищется в обоих полях, regex-символы буквальны."""
        wanted = build_user(
            email="fullname4@example.test", first_name="Алёна", last_name="Иванова"
        )
        build_user(email="fullname5@example.test", first_name="Пётр", last_name="Сидоров")
        for query in ("алёна", "АЛЁНА", "лЁн", "иванова", "иВаНоВа", "ванов"):
            with self.subTest(query=query):
                response = self.client.get("/auth/public-users/", {"fullname": query})
                self.assertEqual([u["id"] for u in response.data["results"]], [wanted.id])
        for query in (".*", "[", "Иванова Несуществующая", "(а+)+$"):
            with self.subTest(query=query):
                response = self.client.get("/auth/public-users/", {"fullname": query})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], 0)

    def test_case_search_is_independent_of_postgres_c_collation(self):
        """C collation не должна превращать кириллицу в регистрозависимый поиск."""
        from django.db.models.functions import Collate
        from users.filters import UserFilter
        from django.contrib.auth import get_user_model

        User = get_user_model()

        wanted = build_user(
            email="fullname6@example.test", first_name="Иван", last_name="Иванов"
        )
        found = User.objects.alias(c_name=Collate("first_name", "C")).filter(
            c_name__regex=UserFilter.fullname_literal_pattern("иВаН")
        )
        self.assertEqual(list(found.values_list("pk", flat=True)), [wanted.pk])

    def test_empty_fullname_and_other_filters_are_preserved(self):
        """Пустой поиск не меняет остальные фильтры и права публичной выдачи."""
        wanted = build_user(
            email="fullname7@example.test",
            first_name="John",
            last_name="Smith",
            user_type=1,
        )
        build_user(
            email="fullname8@example.test",
            first_name="John",
            last_name="Smith",
            user_type=2,
        )
        for query in (" ", "", "JOHN SMITH", "john", "sMiTh"):
            with self.subTest(query=query):
                response = self.client.get(
                    "/auth/public-users/", {"fullname": query, "user_type": 1}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual([u["id"] for u in response.data["results"]], [wanted.id])

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
