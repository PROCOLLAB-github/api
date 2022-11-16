from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import UserManager
from django.db.models import Manager


class CustomUserManager(UserManager):
    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)

        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
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
                "member__preferred_industries",
                "expert__preferred_industries",
                "investor__preferred_industries",
                "achievements",
            )
            .all()
        )

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
