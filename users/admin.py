from datetime import date

import tablib
import urllib.parse
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import path

from core.utils import XlsxFileToExport
from mailing.views import MailingTemplateRender
from users.services.users_activity import UserActivityDataPreparer
from .helpers import send_verification_completed_email, force_verify_user
from .models import (
    CustomUser,
    UserAchievement,
    Member,
    Mentor,
    Expert,
    Investor,
    UserLink,
    UserEducation,
    UserWorkExperience,
    UserSkillConfirmation,
    UserLanguages,
)

from core.admin import SkillToObjectInline

admin.site.register(Permission)


class UserEducationInline(admin.TabularInline):
    model = UserEducation
    extra = 1
    verbose_name = "Образование пользователя"
    verbose_name_plural = "Образование пользователя"


class UserWorkExperienceInline(admin.TabularInline):
    model = UserWorkExperience
    extra = 1
    verbose_name = "Работа пользователя"
    verbose_name_plural = "Работа пользователя"


class UserLanguagesInline(admin.TabularInline):
    model = UserLanguages
    extra = 1
    verbose_name = "Знание языка"
    verbose_name_plural = "Знание языков"


@admin.action(description="Сделать выбранных пользователей подтверждёнными")
def make_active(modeladmin, request, queryset):
    queryset.update(is_active=True)


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
                    "dataset_migration_applied",
                )
            },
        ),
        (
            "Конфиденциальная информация",
            {
                "fields": (
                    "email",
                    "password",
                    "phone_number",
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
        "dataset_migration_applied",
        "v2_speciality",
        "datetime_created",
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
        "v2_speciality__name",
    )

    inlines = [
        SkillToObjectInline,
        UserEducationInline,
        UserWorkExperienceInline,
        UserLanguagesInline,
    ]
    actions = [make_active]

    readonly_fields = ("ordering_score",)
    change_form_template = "users/admin/users_change_form.html"
    change_list_template = "users/admin/users_change_list.html"

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
            path(
                "all-users-email-excel/",
                self.admin_site.admin_view(self.all_users_email_excel),
                name="users_email_excel",
            ),
            path(
                "users-activity-excel/",
                self.admin_site.admin_view(self.get_users_activity),
                name="users_activity_excel",
            ),
        ]
        return custom_urls + default_urls

    def mass_mail(self, request):
        users = CustomUser.objects.all()
        return MailingTemplateRender().render_template(request, None, users, None)

    def all_users_email_excel(self, request):
        users = CustomUser.objects.only("first_name", "last_name", "email").iterator()
        return self.get_export_users_emails(users)

    def mailing(self, request, user_object):
        user = CustomUser.objects.get(pk=user_object)
        users = [user]
        return MailingTemplateRender().render_template(request, None, users, None)

    def force_verify(self, request, object_id):
        user = CustomUser.objects.get(pk=object_id)
        force_verify_user(user)
        return redirect("admin:users_customuser_change", object_id)

    def get_users_activity(self, _) -> HttpResponse:
        activity_prepare = UserActivityDataPreparer()
        xlsx_file_writer = XlsxFileToExport("активность_пользователей.xlsx")
        xlsx_file_writer.write_data_to_xlsx(activity_prepare.get_users_prepared_data())
        binary_data_to_export: bytes = xlsx_file_writer.get_binary_data_from_self_file()
        xlsx_file_writer.delete_self_xlsx_file_from_local_machine()

        encoded_file_name: str = urllib.parse.quote("активность_пользователей.xlsx")
        response = HttpResponse(
            binary_data_to_export,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename*=UTF-8\'\'{encoded_file_name}'

        return response

    def get_export_users_emails(self, users):
        response_data = tablib.Dataset(
            headers=[
                "Имя и фамилия",
                "Возраст",
                "Город",
                "Специальность",
                "Эл. почта",
            ]
        )

        today = date.today()

        date_limit_18 = date(today.year - 18, today.month, today.day)
        date_limit_22 = date(today.year - 22, today.month, today.day)
        # user_ed = UserEducation.objects.select_related(
        #     "user", "user__v2_speciality"
        # ).filter(education_status="Студент")
        users = (
            CustomUser.objects.all()
            .select_related("v2_speciality")
            .filter(
                birthday__gte=date_limit_18,
                birthday__lte=date_limit_22
            )
        )
        # little_mans = users.filter(birthday__lte=date_limit_18)
        # big_mans = users.exclude(id__in=little_mans.values_list("id", flat=True))

        # whole_quality = users.count()
        # quantity_little_mans = little_mans.count()
        # quantity_big_mans = whole_quality - quantity_little_mans

        for user in users:
            response_data.append(
                [
                    user.first_name + " " + user.last_name,
                    (today.year - user.birthday.year)
                    if user.birthday.year
                    else None,
                    user.city,
                    user.v2_speciality
                    if user.v2_speciality
                    else user.speciality,
                    user.email,
                ]
            )

        # for baby in little_mans:
        #     interests = [
        #         collab.project.industry.name if collab.project.industry else ""
        #         for collab in baby.collaborations.all()
        #     ]
        #     if not len(interests):
        #         interests = [
        #             skill_to_obj.skill.name if skill_to_obj.skill else ""
        #             for skill_to_obj in baby.skills.all()
        #         ]
        #     if not len(interests):
        #         interests = baby.key_skills.split(",") if baby.key_skills else []
        #     response_data.append(
        #         [
        #             baby.first_name + " " + baby.last_name,
        #             today.year - baby.birthday.year,
        #             ", ".join(interests),
        #             "; ".join(baby.education.values_list("organization_name", flat=True)),
        #             baby.v2_speciality if baby.v2_speciality else baby.speciality,
        #             baby.email,
        #         ]
        #     )
        #
        # for big_man in big_mans:
        #     industry_names = [
        #         collab.project.industry.name if collab.project.industry else ""
        #         for collab in big_man.collaborations.all()
        #     ]
        #     response_data.append(
        #         [
        #             big_man.first_name + " " + big_man.last_name,
        #             today.year - big_man.birthday.year,
        #             ", ".join(industry_names),
        #             "; ".join(big_man.education.values_list("organization_name", flat=True)),
        #             big_man.v2_speciality
        #             if big_man.v2_speciality
        #             else big_man.speciality,
        #             big_man.email,
        #         ]
        #     )

        # для малолеток указать теги проектов, если нет - навыки
        # для старших - специальность, вуз, учебное заведение

        # for user in users:
        #     response_data.append([user.first_name + " " + user.last_name, user.email])

        binary_data = response_data.export("xlsx")
        file_name = "users"
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{file_name}.xlsx"'},
        )
        response.write(binary_data)
        return response


@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "user")


@admin.register(UserLink)
class UserLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "link")
    list_display_links = ("id", "user", "link")


@admin.register(Expert)
class ExpertAdmin(admin.ModelAdmin):
    list_display = ("id", "user")


@admin.register(UserEducation)
class UserEducationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "organization_name", "entry_year")
    list_display_links = ("id", "organization_name")
    search_fields = ("user__first_name", "user__email")


@admin.register(UserWorkExperience)
class UserWorkExperienceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "organization_name", "entry_year")
    list_display_links = ("id", "organization_name")
    search_fields = ("user__first_name", "user__email")


@admin.register(UserLanguages)
class UserLanguagesAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "language", "language_level")
    list_display_links = ("id", "user")
    search_fields = ("user__first_name", "user__email")


@admin.register(UserSkillConfirmation)
class UserSkillConfirmationAdmin(admin.ModelAdmin):
    list_display = ("id", "get_user_and_skill", "confirmed_by", "confirmed_at")
    search_fields = (
        "skill_to_object__skill__name",
        "confirmed_by__first_name",
        "confirmed_by__last_name",
    )
    raw_id_fields = ("skill_to_object", "confirmed_by")
    readonly_fields = ("confirmed_at",)

    def get_user_and_skill(self, obj):
        try:
            user = obj.skill_to_object.content_object
            skill = obj.skill_to_object.skill
            return f"{user} - {skill}"
        # Possible contingencies with attributes.
        except Exception:
            return ""

    get_user_and_skill.short_description = "User and Skill"
