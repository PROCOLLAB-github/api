from django.contrib import admin

from .models import CustomUser, UserType


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
                    # "key_skills",
                    # "useful_to_project",
                    "status",
                    # "speciality",
                    "city",
                    "region",
                    "organization",
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
        "email",
        "last_name",
        "first_name",
        "id",
    )
    list_display_links = (
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


@admin.register(UserType)
class UserTypeAdmin(admin.ModelAdmin):
    list_display = ("id",)


# TODO display additional fields

# @admin.register(Member)
# class MemberAdmin(admin.ModelAdmin):
#     inlines = (CustomUserInlined,)
#     fieldsets = (
#         (
#             "Дополнительные поля",
#             {
#                 "fields": (
#                     "key_skills",
#                     "useful_to_project",
#                     "speciality",
#                 )
#             },
#         ),
#     )

#     list_display = (
#         "id",
#     )
#     search_fields = (
#         "id",
#     )

#     list_filter = (
#         "id",
#     )
