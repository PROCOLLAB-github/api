from django.contrib import admin

from courses.models import UserTaskAnswer, UserTaskAnswerFile, UserTaskAnswerOption

from .inlines import UserTaskAnswerFileInline, UserTaskAnswerOptionInline


@admin.register(UserTaskAnswer)
class UserTaskAnswerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "task",
        "status",
        "is_correct",
        "submitted_at",
        "reviewed_by",
        "reviewed_at",
    )
    list_display_links = ("id",)
    list_filter = (
        "status",
        "is_correct",
        "task__check_type",
        "task__answer_type",
        "task__lesson__module__course",
    )
    search_fields = (
        "id",
        "user__email",
        "user__first_name",
        "user__last_name",
        "task__title",
    )
    raw_id_fields = ("user", "task", "reviewed_by")
    readonly_fields = ("submitted_at", "datetime_created", "datetime_updated")
    list_select_related = (
        "user",
        "task",
        "reviewed_by",
        "task__lesson",
        "task__lesson__module",
        "task__lesson__module__course",
    )
    inlines = [UserTaskAnswerOptionInline, UserTaskAnswerFileInline]


@admin.register(UserTaskAnswerOption)
class UserTaskAnswerOptionAdmin(admin.ModelAdmin):
    list_display = ("id", "answer", "option", "get_user", "get_task")
    list_display_links = ("id",)
    search_fields = (
        "id",
        "answer__user__email",
        "answer__task__title",
        "option__text",
    )
    raw_id_fields = ("answer", "option")
    list_select_related = ("answer", "option", "answer__user", "answer__task")

    @admin.display(description="Пользователь", ordering="answer__user")
    def get_user(self, obj):
        return obj.answer.user

    @admin.display(description="Задание", ordering="answer__task")
    def get_task(self, obj):
        return obj.answer.task


@admin.register(UserTaskAnswerFile)
class UserTaskAnswerFileAdmin(admin.ModelAdmin):
    list_display = ("id", "answer", "file", "file_name", "file_size", "datetime_uploaded")
    list_display_links = ("id",)
    search_fields = ("id", "file_name", "answer__task__title", "answer__user__email")
    raw_id_fields = ("answer", "file")
    readonly_fields = ("file_name", "file_size", "datetime_uploaded")
    list_select_related = ("answer", "file", "answer__user", "answer__task")
