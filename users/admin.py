from django.contrib import admin

from .models import CustomUser, UserAchievement


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "Аккаунт",
            {"fields": ("user_type",)},
        ),
        (
            "Конфиденциальная информация",
            {
                "fields": (
                    "email",
                    "password",
                )
            },
        ),
        (
            "Персональная информация",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "patronymic",
                    "birthday",
                    "avatar",
                )
            },
        ),
        (
            "Дополнительная информация",
            {
                "fields": (
                    "about_me",
                    "status",
                    "city",
                    "region",
                    "organization",
                    "speciality",
                    "key_skills",
                )
            },
        ),
        (
            "Права доступа",
            {
                "fields": (
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Важные даты",
            {
                "fields": (
                    "last_login",
                    "date_joined",
                )
            },
        ),
    )

    list_display = (
        "id",
        "email",
        "last_name",
        "first_name",
    )
    list_display_links = (
        "id",
        "email",
        "first_name",
        "last_name",
    )

    search_fields = (
        "email",
        "first_name",
        "last_name",
    )

    list_filter = (
        "email",
        "id",
    )


@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "user")
