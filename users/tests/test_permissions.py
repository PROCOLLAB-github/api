from types import SimpleNamespace

from django.test import TestCase
from rest_framework.exceptions import PermissionDenied

from users.models import CustomUser, UserAchievement
from users.permissions import (
    CustomIsAuthenticated,
    IsAchievementOwnerOrReadOnly,
    IsExpert,
    IsExpertPost,
)

from .helpers import build_partner_program, build_user


class UserPermissionsTests(TestCase):
    def test_achievement_owner_can_update_achievement(self):
        user = build_user(email="achievement-owner@example.com")
        achievement = UserAchievement.objects.create(
            user=user,
            title="Победа",
            status="Первое место",
            year=2024,
        )
        request = SimpleNamespace(method="PATCH", user=user)

        self.assertTrue(
            IsAchievementOwnerOrReadOnly().has_object_permission(
                request,
                None,
                achievement,
            )
        )

    def test_non_owner_cannot_update_achievement(self):
        owner = build_user(email="achievement-owner@example.com")
        viewer = build_user(email="achievement-viewer@example.com")
        achievement = UserAchievement.objects.create(
            user=owner,
            title="Победа",
            status="Первое место",
            year=2024,
        )
        request = SimpleNamespace(method="PATCH", user=viewer)

        self.assertFalse(
            IsAchievementOwnerOrReadOnly().has_object_permission(
                request,
                None,
                achievement,
            )
        )

    def test_expert_permission_allows_program_expert(self):
        user = build_user(
            email="expert@example.com",
            user_type=CustomUser.EXPERT,
        )
        program = build_partner_program()
        user.expert.programs.add(program)
        request = SimpleNamespace(user=user)
        view = SimpleNamespace(kwargs={"program_id": program.id})

        self.assertTrue(IsExpert().has_permission(request, view))

    def test_expert_permission_rejects_outsider(self):
        user = build_user(email="member@example.com")
        program = build_partner_program()
        request = SimpleNamespace(user=user)
        view = SimpleNamespace(kwargs={"program_id": program.id})

        with self.assertRaises(PermissionDenied):
            IsExpert().has_permission(request, view)

    def test_expert_post_permission_allows_expert_user_type(self):
        user = build_user(
            email="expert-post@example.com",
            user_type=CustomUser.EXPERT,
        )
        request = SimpleNamespace(user=user)

        self.assertTrue(IsExpertPost().has_permission(request, None))

    def test_custom_is_authenticated_can_be_disabled_by_view_flag(self):
        anonymous_user = SimpleNamespace(is_authenticated=False)
        request = SimpleNamespace(user=anonymous_user)
        view = SimpleNamespace(authentication_off=True)

        self.assertTrue(CustomIsAuthenticated().has_permission(request, view))
