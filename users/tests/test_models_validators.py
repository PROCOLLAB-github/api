from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from users import constants
from users.models import (
    LikesOnProject,
    UserAchievement,
    UserAchievementFile,
    UserLanguages,
    UserWorkExperience,
)
from users.validators import (
    user_birthday_validator,
    user_experience_years_range_validator,
    user_name_validator,
    user_phone_number_validation,
)

from .helpers import build_project, build_user, build_user_file


class UserModelValidationTests(TestCase):
    def test_role_profile_is_created_for_new_user(self):
        user = build_user(email="role@example.com")

        self.assertTrue(hasattr(user, "member"))

    def test_ordering_score_is_recalculated_after_profile_change(self):
        user = build_user(email="ordering@example.com")
        user.about_me = "О себе"
        user.city = "Москва"
        user.save()

        user.refresh_from_db()
        self.assertGreater(user.ordering_score, 0)

    def test_user_language_limit_is_enforced(self):
        user = build_user(email="languages@example.com")
        for language in list(constants.UserLanguagesEnum)[:4]:
            UserLanguages.objects.create(
                user=user,
                language=language.value,
                language_level=constants.UserLanguagesLevels.B1.value,
            )

        with self.assertRaises(DjangoValidationError):
            UserLanguages.objects.create(
                user=user,
                language=constants.UserLanguagesEnum.FRENCH.value,
                language_level=constants.UserLanguagesLevels.B1.value,
            )

    def test_work_experience_rejects_completion_before_entry(self):
        user = build_user(email="experience@example.com")

        with self.assertRaises(DjangoValidationError):
            UserWorkExperience.objects.create(
                user=user,
                organization_name="Компания",
                entry_year=2024,
                completion_year=2020,
            )

    def test_achievement_file_requires_same_owner(self):
        owner = build_user(email="achievement-file-owner@example.com")
        other_user = build_user(email="foreign-file-owner@example.com")
        achievement = UserAchievement.objects.create(
            user=owner,
            title="Победа",
            status="Первое место",
            year=2024,
        )
        foreign_file = build_user_file(
            other_user,
            link="https://cdn.example.com/foreign-achievement.pdf",
        )

        link = UserAchievementFile(achievement=achievement, file=foreign_file)

        with self.assertRaises(DjangoValidationError):
            link.clean()

    def test_project_like_manager_toggles_existing_like(self):
        user = build_user(email="likes@example.com")
        project = build_project(user)

        first_like = LikesOnProject.objects.toggle_like(user, project)
        second_like = LikesOnProject.objects.toggle_like(user, project)

        self.assertTrue(first_like.is_liked)
        self.assertEqual(first_like.id, second_like.id)
        second_like.refresh_from_db()
        self.assertFalse(second_like.is_liked)


class UserValidatorsTests(TestCase):
    def test_birthday_validator_accepts_adult_user(self):
        birthday = timezone.now().date().replace(year=timezone.now().date().year - 20)

        self.assertTrue(user_birthday_validator(birthday))

    def test_birthday_validator_rejects_too_young_user(self):
        birthday = timezone.now().date().replace(year=timezone.now().date().year - 10)

        with self.assertRaises(ValidationError):
            user_birthday_validator(birthday)

    def test_birthday_validator_rejects_user_older_than_100(self):
        birthday = date(timezone.now().date().year - 101, 1, 1)

        with self.assertRaises(ValidationError):
            user_birthday_validator(birthday)

    def test_name_validator_rejects_non_cyrillic_value(self):
        with self.assertRaises(DjangoValidationError):
            user_name_validator("John", field_name="Имя")

    def test_experience_year_validator_rejects_out_of_range_year(self):
        with self.assertRaises(DjangoValidationError):
            user_experience_years_range_validator(1900)

    def test_phone_validator_rejects_invalid_phone_number(self):
        with self.assertRaises(DjangoValidationError):
            user_phone_number_validation("wrong-phone")
