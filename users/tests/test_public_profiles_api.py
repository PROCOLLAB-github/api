from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from core.models import SkillToObject
from users.models import (
    CustomUser,
    UserAchievement,
    UserEducation,
    UserLanguages,
    UserLink,
    UserWorkExperience,
)

from .helpers import (
    attach_skill,
    build_skill,
    build_specialization,
    build_user,
    build_user_file,
)


PUBLIC_LIST_URL = "/auth/profiles/"


class PublicProfileListAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.viewer = build_user(email="viewer@example.com")
        self.client.force_authenticate(self.viewer)

    def test_authenticated_user_can_list_profiles(self):
        target = build_user(
            email="target@example.com",
            first_name="Анна",
            last_name="Смирнова",
            city="Москва",
        )

        response = self.client.get(PUBLIC_LIST_URL)

        self.assertEqual(response.status_code, 200)
        target_item = next(
            item for item in response.data["results"] if item["id"] == target.id
        )
        self.assertEqual(target_item["first_name"], "Анна")
        self.assertEqual(target_item["city"], "Москва")

    def test_anonymous_user_cannot_list_profiles(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(PUBLIC_LIST_URL)

        self.assertEqual(response.status_code, 401)

    def test_pagination_returns_stable_non_overlapping_pages(self):
        for index in range(12):
            build_user(
                email=f"member-{index}@example.com",
                first_name="Имя{:02d}".format(index),
                last_name="Участник",
            )

        first = self.client.get(PUBLIC_LIST_URL, {"limit": 5, "offset": 0})
        second = self.client.get(PUBLIC_LIST_URL, {"limit": 5, "offset": 5})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_ids = [item["id"] for item in first.data["results"]]
        second_ids = [item["id"] for item in second.data["results"]]
        self.assertEqual(len(first_ids), 5)
        self.assertEqual(len(second_ids), 5)
        self.assertFalse(set(first_ids) & set(second_ids))

    def test_search_matches_first_last_and_full_name_in_both_orders(self):
        target = build_user(
            email="search@example.com", first_name="Мария", last_name="Петрова"
        )
        build_user(
            email="unrelated@example.com", first_name="Алексей", last_name="Сидоров"
        )

        for query in ("Мария", "Петрова", "Мария Петрова", "Петрова Мария"):
            with self.subTest(query=query):
                response = self.client.get(PUBLIC_LIST_URL, {"search": query})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [item["id"] for item in response.data["results"]], [target.id]
                )

    def test_confirmed_role_specialization_and_skill_filters_work(self):
        specialization = build_specialization("Backend")
        skill = build_skill("Python")
        target = build_user(
            email="filtered@example.com",
            user_type=CustomUser.EXPERT,
            v2_speciality=specialization,
        )
        attach_skill(target, skill)
        build_user(email="other@example.com")

        response = self.client.get(
            PUBLIC_LIST_URL,
            {
                "user_type": CustomUser.EXPERT,
                "specialization": specialization.id,
                "skill": skill.id,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [target.id])

    def test_multiple_skills_do_not_duplicate_profile(self):
        target = build_user(email="skilled@example.com")
        attach_skill(target, build_skill("Python"))
        attach_skill(target, build_skill("Django"))

        response = self.client.get(PUBLIC_LIST_URL)

        result_ids = [item["id"] for item in response.data["results"]]
        self.assertEqual(result_ids.count(target.id), 1)

    def test_inactive_users_are_excluded(self):
        inactive = build_user(email="inactive@example.com", is_active=False)

        response = self.client.get(PUBLIC_LIST_URL)

        self.assertNotIn(inactive.id, [item["id"] for item in response.data["results"]])

    def test_empty_result_has_paginated_shape(self):
        response = self.client.get(PUBLIC_LIST_URL, {"search": "НетТакогоПользователя"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_list_query_count_does_not_grow_with_profiles_or_skills(self):
        content_type = ContentType.objects.get_for_model(CustomUser)
        skills = [build_skill(f"Навык {index}") for index in range(3)]
        for index in range(8):
            user = build_user(email=f"queries-{index}@example.com")
            SkillToObject.objects.bulk_create(
                [
                    SkillToObject(
                        skill=skill,
                        content_type=content_type,
                        object_id=user.id,
                    )
                    for skill in skills
                ]
            )

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(PUBLIC_LIST_URL, {"limit": 20})

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 4)


class PublicProfileDetailAPITests(TestCase):
    forbidden_keys = {
        "email",
        "phone",
        "phone_number",
        "birthday",
        "password",
        "is_active",
        "is_staff",
        "is_superuser",
        "is_online",
        "last_login",
        "date_joined",
        "onboarding_stage",
        "verification_date",
        "ordering_score",
        "dataset_migration_applied",
        "user",
    }

    def setUp(self):
        self.client = APIClient()
        self.viewer = build_user(email="viewer-detail@example.com")
        self.client.force_authenticate(self.viewer)

    def _assert_forbidden_keys_absent(self, value):
        if isinstance(value, dict):
            self.assertFalse(self.forbidden_keys & set(value.keys()))
            for nested in value.values():
                self._assert_forbidden_keys_absent(nested)
        elif isinstance(value, list):
            for nested in value:
                self._assert_forbidden_keys_absent(nested)

    def test_public_detail_returns_only_allow_list_in_expected_format(self):
        specialization = build_specialization("Аналитик")
        user = build_user(
            email="private@example.com",
            first_name="Ирина",
            last_name="Орлова",
            patronymic="Сергеевна",
            city="Казань",
            about_me="Работаю с данными",
            phone_number="+79991234567",
            v2_speciality=specialization,
        )
        attach_skill(user, build_skill("Аналитика"))
        UserLink.objects.create(user=user, link="https://example.com/irina")
        UserEducation.objects.create(user=user, organization_name="Университет")
        UserWorkExperience.objects.create(user=user, organization_name="Компания")
        UserLanguages.objects.create(
            user=user, language="Английский", language_level="B2"
        )
        achievement = UserAchievement.objects.create(
            user=user, title="Хакатон", status="Победитель", year=2025
        )
        achievement.files.add(
            build_user_file(user, link="https://cdn.example.com/diploma.pdf")
        )

        response = self.client.get(f"/auth/profiles/{user.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data.keys()),
            {
                "id",
                "first_name",
                "last_name",
                "avatar",
                "city",
                "user_type",
                "user_type_label",
                "specialization",
                "skills",
                "patronymic",
                "about_me",
                "links",
                "education",
                "work_experience",
                "user_languages",
                "achievements",
            },
        )
        self.assertEqual(response.data["specialization"]["id"], specialization.id)
        self.assertEqual(response.data["achievements"][0]["files"][0]["name"], "file")
        self._assert_forbidden_keys_absent(response.data)

    def test_anonymous_user_cannot_open_public_detail(self):
        user = build_user(email="anonymous-target@example.com")
        self.client.force_authenticate(user=None)

        response = self.client.get(f"/auth/profiles/{user.id}/")

        self.assertEqual(response.status_code, 401)

    def test_unknown_profile_returns_404(self):
        response = self.client.get("/auth/profiles/999999/")

        self.assertEqual(response.status_code, 404)

    def test_inactive_profile_returns_safe_404(self):
        user = build_user(email="hidden@example.com", is_active=False)

        response = self.client.get(f"/auth/profiles/{user.id}/")

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, user.email, status_code=404)


class OwnProfileUpdateRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = build_user(email="owner-profile@example.com")
        self.client.force_authenticate(self.user)

    def test_owner_updates_profile_and_avatar_url(self):
        response = self.client.patch(
            f"/auth/users/{self.user.id}/",
            {
                "first_name": "Новое имя",
                "avatar": "https://cdn.example.com/avatar.webp",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Новое имя")
        self.assertEqual(self.user.avatar, "https://cdn.example.com/avatar.webp")

    def test_user_cannot_update_another_profile(self):
        other = build_user(email="other-profile@example.com")

        response = self.client.patch(
            f"/auth/users/{other.id}/", {"first_name": "Подмена"}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        other.refresh_from_db()
        self.assertNotEqual(other.first_name, "Подмена")

    def test_auth_and_service_fields_cannot_be_changed(self):
        original_email = self.user.email
        original_stage = self.user.onboarding_stage

        response = self.client.patch(
            f"/auth/users/{self.user.id}/",
            {
                "email": "attacker@example.com",
                "is_active": False,
                "is_staff": True,
                "is_superuser": True,
                "onboarding_stage": None,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, original_email)
        self.assertTrue(self.user.is_active)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(self.user.onboarding_stage, original_stage)

    def test_invalid_specialization_id_is_rejected(self):
        response = self.client.patch(
            f"/auth/users/{self.user.id}/",
            {"v2_speciality_id": 999999},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_nested_collection_rolls_back_whole_profile_update(self):
        self.user.first_name = "До изменения"
        self.user.save(update_fields=["first_name"])

        response = self.client.patch(
            f"/auth/users/{self.user.id}/",
            {
                "first_name": "Не должно сохраниться",
                "user_languages": [
                    {"language": "Английский", "language_level": "B1"},
                    {"language": "Английский", "language_level": "B2"},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "До изменения")
        self.assertFalse(UserLanguages.objects.filter(user=self.user).exists())
