from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import UserManager
from django.db.models import Manager

from users.constants import MEMBER


class CustomUserManager(UserManager):
    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)

        return self._create_user(email, password, **extra_fields)

    def get_active(self):
        return self.get_queryset().filter(is_active=True).prefetch_related("member")

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("birthday", "1900-01-01")
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        assert extra_fields.get("is_staff"), "Superuser must be assigned to is_staff=True"
        assert extra_fields.get(
            "is_superuser"
        ), "Superuser must be assigned to is_superuser=True"
        assert extra_fields.get(
            "is_active"
        ), "Superuser must be assigned to is_active=True"

        return self._create_user(email, password, **extra_fields)

    def get_users_for_detail_view(self):
        return (
            self.get_queryset()
            .select_related("member", "investor", "expert", "mentor")
            .prefetch_related(
                "achievements",
                "collaborations",
            )
            .all()
        )

    def get_members(self):
        return self.get_queryset().filter(user_type=MEMBER)

    def _create_user(self, email, password, **extra_fields):
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.password = make_password(password)
        user.save()
        return user


class UserAchievementManager(Manager):
    def get_achievements_for_list_view(self):
        return (
            self.get_queryset()
            .select_related("user")
            .only("id", "title", "status", "user__id")
        )

    def get_achievements_for_detail_view(self):
        return (
            self.get_queryset()
            .select_related("user")
            .only("id", "title", "status", "user")
        )


class LikesOnProjectManager(Manager):
    def get_likes_for_list_view(self):
        return (
            self.get_queryset()
            .select_related("user")
            .only("id", "user__id", "project__id")
        )

    def get_or_create(self, user, project):
        return super().get_or_create(user=user, project=project)

    def toggle_like(self, user, project):
        like, created = self.get_or_create(user=user, project=project)
        if not created:
            like.toggle_like()
        return like
