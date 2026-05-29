from django.test import TestCase
from rest_framework.test import APIClient

from users.models import UserAchievement

from .helpers import build_user, build_user_file


class UserAchievementAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = build_user(email="achievements@example.com")
        self.client.force_authenticate(user=self.user)

    def test_user_can_create_achievement_with_owned_file(self):
        user_file = build_user_file(self.user)

        response = self.client.post(
            "/auth/users/achievements/",
            {
                "title": "Победа",
                "status": "Первое место",
                "year": 2024,
                "file_links": [user_file.link],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        achievement = UserAchievement.objects.get(user=self.user)
        self.assertEqual(achievement.files.get(), user_file)

    def test_user_cannot_create_achievement_for_another_user(self):
        other_user = build_user(email="achievement-owner@example.com")

        response = self.client.post(
            "/auth/users/achievements/",
            {
                "user": other_user.id,
                "title": "Победа",
                "status": "Первое место",
                "year": 2024,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserAchievement.objects.filter(user=other_user).exists())

    def test_user_cannot_attach_foreign_file_to_achievement(self):
        other_user = build_user(email="file-owner@example.com")
        foreign_file = build_user_file(
            other_user,
            link="https://cdn.example.com/foreign.pdf",
        )

        response = self.client.post(
            "/auth/users/achievements/",
            {
                "title": "Победа",
                "status": "Первое место",
                "year": 2024,
                "file_links": [foreign_file.link],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserAchievement.objects.filter(user=self.user).exists())

    def test_profile_update_replaces_achievements_and_validates_owned_files(self):
        old_achievement = UserAchievement.objects.create(
            user=self.user,
            title="Старое достижение",
            status="Участник",
            year=2023,
        )
        user_file = build_user_file(self.user)

        response = self.client.patch(
            f"/auth/users/{self.user.id}/",
            {
                "achievements": [
                    {
                        "title": "Новое достижение",
                        "status": "Победитель",
                        "year": 2024,
                        "file_links": [user_file.link],
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserAchievement.objects.filter(id=old_achievement.id).exists())
        achievement = UserAchievement.objects.get(user=self.user)
        self.assertEqual(achievement.title, "Новое достижение")
        self.assertEqual(achievement.files.get(), user_file)

    def test_profile_update_rejects_duplicate_achievements(self):
        response = self.client.patch(
            f"/auth/users/{self.user.id}/",
            {
                "achievements": [
                    {"title": "Победа", "status": "Первое место", "year": 2024},
                    {"title": "Победа", "status": "Первое место", "year": 2024},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserAchievement.objects.filter(user=self.user).exists())
