from django.contrib import admin

from courses.models import UserCourseProgress, UserLessonProgress, UserModuleProgress


@admin.register(UserCourseProgress)
class UserCourseProgressAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "course",
        "status",
        "percent",
        "started_at",
        "completed_at",
        "last_visit_at",
        "datetime_updated",
    )
    list_display_links = ("id",)
    list_filter = ("status", "course")
    search_fields = (
        "id",
        "user__email",
        "user__first_name",
        "user__last_name",
        "course__title",
    )
    raw_id_fields = ("user", "course")
    readonly_fields = ("datetime_created", "datetime_updated")
    list_select_related = ("user", "course")


@admin.register(UserModuleProgress)
class UserModuleProgressAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "module",
        "get_course",
        "status",
        "percent",
        "started_at",
        "completed_at",
        "datetime_updated",
    )
    list_display_links = ("id",)
    list_filter = ("status", "module__course")
    search_fields = (
        "id",
        "user__email",
        "user__first_name",
        "user__last_name",
        "module__title",
        "module__course__title",
    )
    raw_id_fields = ("user", "module")
    readonly_fields = ("datetime_created", "datetime_updated")
    list_select_related = ("user", "module", "module__course")

    @admin.display(description="Курс", ordering="module__course__title")
    def get_course(self, obj):
        return obj.module.course


@admin.register(UserLessonProgress)
class UserLessonProgressAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "lesson",
        "get_module",
        "get_course",
        "status",
        "percent",
        "current_task",
        "started_at",
        "completed_at",
        "datetime_updated",
    )
    list_display_links = ("id",)
    list_filter = ("status", "lesson__module__course")
    search_fields = (
        "id",
        "user__email",
        "user__first_name",
        "user__last_name",
        "lesson__title",
        "lesson__module__title",
        "lesson__module__course__title",
    )
    raw_id_fields = ("user", "lesson", "current_task")
    readonly_fields = ("datetime_created", "datetime_updated")
    list_select_related = (
        "user",
        "lesson",
        "lesson__module",
        "lesson__module__course",
        "current_task",
    )

    @admin.display(description="Модуль", ordering="lesson__module__title")
    def get_module(self, obj):
        return obj.lesson.module

    @admin.display(description="Курс", ordering="lesson__module__course__title")
    def get_course(self, obj):
        return obj.lesson.module.course
