from django.test import TestCase
from rest_framework.test import APIClient

from core.models import SkillToObject
from users.constants import UserLanguagesEnum, UserLanguagesLevels
from users.models import CustomUser, UserEducation, UserLanguages, UserLink, UserWorkExperience

from .helpers import build_skill, build_specialization, build_user


class UserProfileUpdateAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = build_user(email="profile@example.com")
        self.client.force_authenticate(user=self.user)

    def test_owner_can_update_profile_related_data(self):
        skill = build_skill("Django")
        specialization = build_specialization("Backend")

        response = self.client.patch(
            f"/auth/users/{self.user.id}/",
            {
                "first_name": "Сергей",
                "city": "Москва",
                "phone_number": "+79991234567",
                "v2_speciality_id": specialization.id,
                "skills_ids": [skill.id],
                "education": [
                    {
                        "organization_name": "Университет",
                        "description": "Информатика",
                        "entry_year": 2018,
                        "completion_year": 2022,
                        "education_level": "Высшее образование – бакалавриат, специалитет",
                        "education_status": "Выпускник",
                    }
                ],
                "work_experience": [
                    {
                        "organization_name": "Компания",
                        "description": "Backend",
                        "entry_year": 2022,
                        "completion_year": 2024,
                        "job_position": "Разработчик",
                    }
                ],
                "user_languages": [
                    {
                        "language": UserLanguagesEnum.ENGLISH.value,
                        "language_level": UserLanguagesLevels.B2.value,
                    }
                ],
                "links": ["https://example.com/profile"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Сергей")
        self.assertEqual(self.user.v2_speciality_id, specialization.id)
        self.assertEqual(UserEducation.objects.filter(user=self.user).count(), 1)
        self.assertEqual(UserWorkExperience.objects.filter(user=self.user).count(), 1)
        self.assertEqual(UserLanguages.objects.filter(user=self.user).count(), 1)
        self.assertEqual(UserLink.objects.filter(user=self.user).count(), 1)
        self.assertTrue(
            SkillToObject.objects.filter(object_id=self.user.id, skill=skill).exists()
        )

    def test_owner_cannot_add_duplicate_languages(self):
        response = self.client.patch(
            f"/auth/users/{self.user.id}/",
            {
                "user_languages": [
                    {
                        "language": UserLanguagesEnum.ENGLISH.value,
                        "language_level": UserLanguagesLevels.B1.value,
                    },
                    {
                        "language": UserLanguagesEnum.ENGLISH.value,
                        "language_level": UserLanguagesLevels.B2.value,
                    },
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserLanguages.objects.filter(user=self.user).exists())

    def test_user_cannot_update_another_profile(self):
        other_user = build_user(email="other@example.com")

        response = self.client.patch(
            f"/auth/users/{other_user.id}/",
            {"first_name": "Петр"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        other_user.refresh_from_db()
        self.assertNotEqual(other_user.first_name, "Петр")

    def test_phone_number_is_hidden_from_other_users(self):
        self.user.phone_number = "+79991234567"
        self.user.save()
        viewer = build_user(email="viewer@example.com")
        self.client.force_authenticate(user=viewer)

        response = self.client.get(f"/auth/users/{self.user.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("phone_number", response.data)

    def test_member_user_type_is_immutable_in_profile_update(self):
        response = self.client.patch(
            f"/auth/users/{self.user.id}/",
            {"user_type": CustomUser.EXPERT},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.user_type, CustomUser.MEMBER)
