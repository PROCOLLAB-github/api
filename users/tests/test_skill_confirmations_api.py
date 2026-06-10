from django.test import TestCase
from rest_framework.test import APIClient

from users.models import UserSkillConfirmation

from .helpers import attach_skill, build_skill, build_user


class UserSkillConfirmationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = build_user(email="skill-owner@example.com")
        self.confirming_user = build_user(email="confirmer@example.com")
        self.skill = build_skill("Python")
        self.skill_to_object = attach_skill(self.user, self.skill)

    def test_user_can_confirm_another_user_skill(self):
        self.client.force_authenticate(user=self.confirming_user)

        response = self.client.post(
            f"/auth/users/{self.user.id}/approve_skill/{self.skill.id}/"
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            UserSkillConfirmation.objects.filter(
                skill_to_object=self.skill_to_object,
                confirmed_by=self.confirming_user,
            ).exists()
        )

    def test_user_cannot_confirm_own_skill(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            f"/auth/users/{self.user.id}/approve_skill/{self.skill.id}/"
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserSkillConfirmation.objects.exists())

    def test_user_can_delete_own_skill_confirmation(self):
        UserSkillConfirmation.objects.create(
            skill_to_object=self.skill_to_object,
            confirmed_by=self.confirming_user,
        )
        self.client.force_authenticate(user=self.confirming_user)

        response = self.client.delete(
            f"/auth/users/{self.user.id}/approve_skill/{self.skill.id}/"
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(UserSkillConfirmation.objects.exists())

    def test_user_cannot_delete_another_user_skill_confirmation(self):
        other_user = build_user(email="other-confirmer@example.com")
        UserSkillConfirmation.objects.create(
            skill_to_object=self.skill_to_object,
            confirmed_by=other_user,
        )
        self.client.force_authenticate(user=self.confirming_user)

        response = self.client.delete(
            f"/auth/users/{self.user.id}/approve_skill/{self.skill.id}/"
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(UserSkillConfirmation.objects.exists())
