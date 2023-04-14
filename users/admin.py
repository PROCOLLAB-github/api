from django.conf import settings
from django.contrib import admin

from .models import CustomUser, UserAchievement, Member, Mentor, Expert, Investor


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "Аккаунт",
            {
                "fields": (
                    "user_type",
                    "onboarding_stage",
                )
            },
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

    list_display = ("id", "email", "last_name", "first_name", "is_active")
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
        "is_staff",
        "is_superuser",
        "city",
    )

    def save_model(self, request, obj, form, change):
        # if user_type changed, then delete all related fields
        if change:
            old_user = CustomUser.objects.get(id=obj.id)
            if obj.user_type != old_user.user_type:
                try:
                    if old_user.user_type == CustomUser.MEMBER:
                        old_user.member.delete()
                    elif old_user.user_type == CustomUser.MENTOR:
                        old_user.mentor.delete()
                    elif old_user.user_type == CustomUser.EXPERT:
                        old_user.expert.delete()
                    elif old_user.user_type == CustomUser.INVESTOR:
                        old_user.investor.delete()
                except Exception:
                    print(f"User type `{old_user.user_type}` is not supported!")

                if obj.user_type == CustomUser.MEMBER:
                    Member.objects.create(user=old_user)
                elif obj.user_type == CustomUser.MENTOR:
                    Mentor.objects.create(user=old_user)
                elif obj.user_type == CustomUser.EXPERT:
                    Expert.objects.create(user=old_user)
                elif obj.user_type == CustomUser.INVESTOR:
                    Investor.objects.create(user=old_user)

            # # set hashed password
            # obj.set_password(obj.password)

            if settings.DEBUG:
                obj.is_active = True

        super().save_model(request, obj, form, change)


@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "user")
