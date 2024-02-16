from django.conf import settings
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path

from mailing.views import MailingTemplateRender
from .helpers import send_verification_completed_email, force_verify_user
from .models import (
    CustomUser,
    UserAchievement,
    Member,
    Mentor,
    Expert,
    Investor,
    UserLink,
)


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "Аккаунт",
            {
                "fields": (
                    "user_type",
                    "verification_date",
                    "ordering_score",
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
                    "v2_speciality",
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
            {"fields": ("last_login", "date_joined")},
        ),
    )

    list_display = (
        "id",
        "email",
        "last_name",
        "first_name",
        "ordering_score",
        "is_active",
        "v2_speciality",
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
        "is_staff",
        "is_superuser",
        "city",
    )

    readonly_fields = ("ordering_score",)
    change_form_template = "users/admin/users_change_form.html"

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
                    # ???
                    pass

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

            # if user has just been confirmed
            if obj.verification_date != old_user.verification_date:
                send_verification_completed_email(obj)

        super().save_model(request, obj, form, change)

    def get_urls(self):
        default_urls = super(CustomUserAdmin, self).get_urls()
        custom_urls = [
            path(
                "mailing/<int:user_object>/",
                self.admin_site.admin_view(self.mailing),
                name="user_mailing",
            ),
            path(
                "force_verify/<int:object_id>/",
                self.admin_site.admin_view(self.force_verify),
                name="force_verify",
            ),
            path(
                "mailing/",
                self.admin_site.admin_view(self.mass_mail),
                name="user_mass_mail",
            ),
        ]
        return custom_urls + default_urls

    def mass_mail(self, request):
        users = CustomUser.objects.all()
        return MailingTemplateRender().render_template(request, None, users, None)

    def mailing(self, request, user_object):
        user = CustomUser.objects.get(pk=user_object)
        users = [user]
        return MailingTemplateRender().render_template(request, None, users, None)

    def force_verify(self, request, object_id):
        user = CustomUser.objects.get(pk=object_id)
        force_verify_user(user)
        return redirect("admin:users_customuser_change", object_id)


@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "user")


@admin.register(UserLink)
class UserLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "link")
    list_display_links = ("id", "user", "link")
