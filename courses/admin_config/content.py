from django.contrib import admin

from courses.models import Course, CourseLesson, CourseModule, CourseTask, CourseTaskOption

from .forms import CourseAdminForm, CourseModuleAdminForm, CourseTaskAdminForm
from .helpers import UserFileUploadAdminMixin
from .inlines import (
    CourseLessonInline,
    CourseModuleInline,
    CourseTaskOptionInline,
)


@admin.register(Course)
class CourseAdmin(UserFileUploadAdminMixin, admin.ModelAdmin):
    form = CourseAdminForm
    list_display = (
        "id",
        "title",
        "access_type",
        "status",
        "is_completed",
        "start_date",
        "end_date",
        "partner_program",
        "datetime_created",
    )
    list_display_links = ("id", "title")
    list_filter = ("access_type", "status", "is_completed")
    search_fields = ("id", "title", "partner_program__name")
    raw_id_fields = ("partner_program",)
    readonly_fields = ("completed_at", "datetime_created", "datetime_updated")
    list_select_related = ("partner_program",)
    inlines = [CourseModuleInline]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    "description",
                    "access_type",
                    "partner_program",
                    "status",
                    "is_completed",
                )
            },
        ),
        (
            "Период",
            {"fields": ("start_date", "end_date", "completed_at")},
        ),
        (
            "Файлы",
            {
                "fields": (
                    "avatar_file",
                    "avatar_upload",
                    "card_cover_file",
                    "card_cover_upload",
                    "header_cover_file",
                    "header_cover_upload",
                )
            },
        ),
        (
            "Системные поля",
            {"fields": ("datetime_created", "datetime_updated")},
        ),
    )

    def save_model(self, request, obj, form, change):
        avatar_upload = form.cleaned_data.get("avatar_upload")
        if avatar_upload:
            obj.avatar_file = self.create_user_file(request, avatar_upload)

        card_cover_upload = form.cleaned_data.get("card_cover_upload")
        if card_cover_upload:
            obj.card_cover_file = self.create_user_file(request, card_cover_upload)

        header_cover_upload = form.cleaned_data.get("header_cover_upload")
        if header_cover_upload:
            obj.header_cover_file = self.create_user_file(request, header_cover_upload)

        super().save_model(request, obj, form, change)


@admin.register(CourseModule)
class CourseModuleAdmin(UserFileUploadAdminMixin, admin.ModelAdmin):
    form = CourseModuleAdminForm
    list_display = (
        "id",
        "title",
        "course",
        "status",
        "start_date",
        "order",
        "datetime_created",
    )
    list_display_links = ("id", "title")
    list_filter = ("status", "course")
    search_fields = ("id", "title", "course__title")
    raw_id_fields = ("course",)
    readonly_fields = ("datetime_created", "datetime_updated")
    list_select_related = ("course",)
    inlines = [CourseLessonInline]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "course",
                    "title",
                    "start_date",
                    "status",
                    "order",
                )
            },
        ),
        (
            "Файлы",
            {"fields": ("avatar_file", "avatar_upload")},
        ),
        (
            "Системные поля",
            {"fields": ("datetime_created", "datetime_updated")},
        ),
    )

    def save_model(self, request, obj, form, change):
        avatar_upload = form.cleaned_data.get("avatar_upload")
        if avatar_upload:
            obj.avatar_file = self.create_user_file(request, avatar_upload)
        super().save_model(request, obj, form, change)


@admin.register(CourseLesson)
class CourseLessonAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "module",
        "get_course",
        "status",
        "order",
        "datetime_created",
    )
    list_display_links = ("id", "title")
    list_filter = ("status", "module__course")
    search_fields = ("id", "title", "module__title", "module__course__title")
    raw_id_fields = ("module",)
    readonly_fields = ("datetime_created", "datetime_updated")
    list_select_related = ("module", "module__course")

    @admin.display(description="Курс", ordering="module__course__title")
    def get_course(self, obj):
        return obj.module.course


@admin.register(CourseTask)
class CourseTaskAdmin(UserFileUploadAdminMixin, admin.ModelAdmin):
    form = CourseTaskAdminForm
    list_display = (
        "id",
        "title",
        "lesson",
        "get_module",
        "get_course",
        "task_kind",
        "status",
        "question_type",
        "answer_type",
        "order",
    )
    list_display_links = ("id", "title")
    list_filter = (
        "status",
        "task_kind",
        "check_type",
        "question_type",
        "answer_type",
        "lesson__module__course",
    )
    search_fields = (
        "id",
        "title",
        "lesson__title",
        "lesson__module__title",
        "lesson__module__course__title",
    )
    raw_id_fields = ("lesson",)
    readonly_fields = ("datetime_created", "datetime_updated")
    list_select_related = ("lesson", "lesson__module", "lesson__module__course")
    inlines = [CourseTaskOptionInline]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "lesson",
                    "title",
                    "status",
                    "task_kind",
                    "order",
                )
            },
        ),
        (
            "Типы задания",
            {
                "fields": (
                    "check_type",
                    "informational_type",
                    "question_type",
                    "answer_type",
                )
            },
        ),
        (
            "Контент",
            {
                "fields": (
                    "body_text",
                    "answer_title",
                    "video_url",
                    "image_file",
                    "image_upload",
                    "attachment_file",
                    "attachment_upload",
                )
            },
        ),
        (
            "Системные поля",
            {"fields": ("datetime_created", "datetime_updated")},
        ),
    )

    def save_model(self, request, obj, form, change):
        image_upload = form.cleaned_data.get("image_upload")
        if image_upload:
            obj.image_file = self.create_user_file(request, image_upload)

        attachment_upload = form.cleaned_data.get("attachment_upload")
        if attachment_upload:
            obj.attachment_file = self.create_user_file(request, attachment_upload)

        super().save_model(request, obj, form, change)

    @admin.display(description="Модуль", ordering="lesson__module__title")
    def get_module(self, obj):
        return obj.lesson.module

    @admin.display(description="Курс", ordering="lesson__module__course__title")
    def get_course(self, obj):
        return obj.lesson.module.course


@admin.register(CourseTaskOption)
class CourseTaskOptionAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "text", "is_correct", "order", "datetime_created")
    list_display_links = ("id", "text")
    list_filter = ("is_correct", "task__answer_type")
    search_fields = ("id", "text", "task__title")
    raw_id_fields = ("task",)
    readonly_fields = ("datetime_created", "datetime_updated")
    list_select_related = ("task",)
