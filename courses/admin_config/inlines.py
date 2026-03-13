from django.contrib import admin

from courses.models import (
    CourseLesson,
    CourseModule,
    CourseTask,
    CourseTaskOption,
    UserTaskAnswerFile,
    UserTaskAnswerOption,
)

from .forms import OrderUniqueInlineFormSet


class CourseModuleInline(admin.TabularInline):
    model = CourseModule
    formset = OrderUniqueInlineFormSet
    extra = 0
    fields = ("id", "title", "start_date", "status", "order")
    readonly_fields = ("id",)
    show_change_link = True
    ordering = ("order", "id")


class CourseLessonInline(admin.TabularInline):
    model = CourseLesson
    formset = OrderUniqueInlineFormSet
    extra = 0
    fields = ("id", "title", "status", "order")
    readonly_fields = ("id",)
    show_change_link = True
    ordering = ("order", "id")


class CourseTaskInline(admin.TabularInline):
    model = CourseTask
    formset = OrderUniqueInlineFormSet
    extra = 0
    fields = ("id", "title", "task_kind", "status", "order")
    readonly_fields = ("id",)
    show_change_link = True
    ordering = ("order", "id")


class CourseTaskOptionInline(admin.TabularInline):
    model = CourseTaskOption
    formset = OrderUniqueInlineFormSet
    extra = 0
    fields = ("id", "text", "is_correct", "order")
    readonly_fields = ("id",)
    ordering = ("order", "id")


class UserTaskAnswerOptionInline(admin.TabularInline):
    model = UserTaskAnswerOption
    extra = 0
    fields = ("id", "option")
    readonly_fields = ("id",)
    raw_id_fields = ("option",)


class UserTaskAnswerFileInline(admin.TabularInline):
    model = UserTaskAnswerFile
    extra = 0
    fields = ("id", "file", "file_name", "file_size", "datetime_uploaded")
    readonly_fields = ("id", "file_name", "file_size", "datetime_uploaded")
    raw_id_fields = ("file",)
