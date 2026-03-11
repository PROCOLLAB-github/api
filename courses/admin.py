from django.contrib import admin
from django import forms
from django.forms.models import BaseInlineFormSet
from types import MethodType

from files.models import UserFile
from files.service import CDN, SelectelSwiftStorage

from .models import (
    Course,
    CourseLesson,
    CourseModule,
    CourseTask,
    CourseTaskOption,
    UserCourseProgress,
    UserLessonProgress,
    UserModuleProgress,
    UserTaskAnswer,
    UserTaskAnswerFile,
    UserTaskAnswerOption,
)
from .models.content import looks_like_image_file

# Admin-only captions for sections in app index
CourseModule._meta.verbose_name = "Модуль"
CourseModule._meta.verbose_name_plural = "Модули"
CourseLesson._meta.verbose_name = "Урок"
CourseLesson._meta.verbose_name_plural = "Уроки"
CourseTask._meta.verbose_name = "Задание"
CourseTask._meta.verbose_name_plural = "Задания"
CourseTaskOption._meta.verbose_name = "Вариант ответа"
CourseTaskOption._meta.verbose_name_plural = "Варианты ответов"
UserTaskAnswer._meta.verbose_name = "Ответ пользователя"
UserTaskAnswer._meta.verbose_name_plural = "Ответы пользователя"
UserTaskAnswerOption._meta.verbose_name = "Выбранный вариант"
UserTaskAnswerOption._meta.verbose_name_plural = "Выбранные варианты"
UserTaskAnswerFile._meta.verbose_name = "Файл"
UserTaskAnswerFile._meta.verbose_name_plural = "Файлы"
UserCourseProgress._meta.verbose_name = "Прогресс курса"
UserCourseProgress._meta.verbose_name_plural = "Прогресс курсов"
UserModuleProgress._meta.verbose_name = "Прогресс модуля"
UserModuleProgress._meta.verbose_name_plural = "Прогресс модулей"
UserLessonProgress._meta.verbose_name = "Прогресс урока"
UserLessonProgress._meta.verbose_name_plural = "Прогресс уроков"

_COURSES_MODEL_ORDER = {
    "Course": 1,
    "CourseModule": 2,
    "CourseLesson": 3,
    "CourseTask": 4,
    "CourseTaskOption": 5,
    "UserTaskAnswer": 6,
    "UserTaskAnswerOption": 7,
    "UserTaskAnswerFile": 8,
    "UserCourseProgress": 9,
    "UserModuleProgress": 10,
    "UserLessonProgress": 11,
}


def _courses_get_app_list(self, request, app_label=None):
    app_list = self._courses_original_get_app_list(request, app_label)
    for app in app_list:
        if app.get("app_label") == "courses":
            app["models"].sort(
                key=lambda model_info: _COURSES_MODEL_ORDER.get(
                    model_info.get("object_name"),
                    999,
                )
            )
    return app_list


if not getattr(admin.site, "_courses_order_patched", False):
    admin.site._courses_original_get_app_list = admin.site.get_app_list
    admin.site.get_app_list = MethodType(_courses_get_app_list, admin.site)
    admin.site._courses_order_patched = True


class OrderUniqueInlineFormSet(BaseInlineFormSet):
    duplicate_field_error = "Такой порядковый номер уже используется в этом разделе."
    duplicate_form_error = "Найдены дублирующиеся значения. Исправьте строки ниже."

    def get_unique_error_message(self, unique_check):
        if "order" in unique_check:
            return self.duplicate_field_error
        return super().get_unique_error_message(unique_check)

    def get_form_error(self):
        return self.duplicate_form_error

    def clean(self):
        super().clean()
        order_to_form = {}
        has_duplicates = False

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue

            order_value = form.cleaned_data.get("order")
            if order_value in (None, ""):
                continue

            previous_form = order_to_form.get(order_value)
            if previous_form is not None:
                previous_form.add_error("order", self.duplicate_field_error)
                form.add_error("order", self.duplicate_field_error)
                has_duplicates = True
            else:
                order_to_form[order_value] = form

        if has_duplicates:
            raise forms.ValidationError(self.duplicate_form_error)


class CourseAdminForm(forms.ModelForm):
    avatar_upload = forms.FileField(
        required=False,
        label="Аватар (загрузить файл)",
    )
    card_cover_upload = forms.FileField(
        required=False,
        label="Обложка карточки (загрузить файл)",
    )
    header_cover_upload = forms.FileField(
        required=False,
        label="Обложка шапки (загрузить файл)",
    )

    class Meta:
        model = Course
        fields = "__all__"


class CourseTaskAdminForm(forms.ModelForm):
    image_upload = forms.FileField(
        required=False,
        label="Изображение (загрузить файл)",
    )
    attachment_upload = forms.FileField(
        required=False,
        label="Файл (загрузить)",
    )

    class Meta:
        model = CourseTask
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        image_upload = cleaned_data.get("image_upload")
        attachment_upload = cleaned_data.get("attachment_upload")
        if image_upload and not looks_like_image_file(
            mime_type=getattr(image_upload, "content_type", ""),
            extension=getattr(image_upload, "name", "").rsplit(".", 1)[-1],
        ):
            self.add_error(
                "image_upload",
                "В поле изображения можно загрузить только файл изображения.",
            )

        # Preserve the fact that a file was provided so model validation
        # doesn't add a second "required image" error for the same field.
        self.instance._has_pending_image_upload = bool(image_upload)
        self.instance._has_pending_attachment_upload = bool(attachment_upload)
        return cleaned_data


class CourseModuleAdminForm(forms.ModelForm):
    avatar_upload = forms.FileField(
        required=False,
        label="Аватар (загрузить файл)",
    )

    class Meta:
        model = CourseModule
        fields = "__all__"


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


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
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
    cdn = CDN(storage=SelectelSwiftStorage())

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
            {
                "fields": (
                    "start_date",
                    "end_date",
                    "completed_at",
                )
            },
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
            {
                "fields": (
                    "datetime_created",
                    "datetime_updated",
                )
            },
        ),
    )

    def _create_user_file(self, request, uploaded_file):
        info = self.cdn.upload(uploaded_file, request.user, quality=100)
        return UserFile.objects.create(
            link=info.url,
            user=request.user,
            name=info.name,
            size=info.size,
            extension=info.extension,
            mime_type=info.mime_type,
        )

    def save_model(self, request, obj, form, change):
        avatar_upload = form.cleaned_data.get("avatar_upload")
        if avatar_upload:
            obj.avatar_file = self._create_user_file(request, avatar_upload)

        card_cover_upload = form.cleaned_data.get("card_cover_upload")
        if card_cover_upload:
            obj.card_cover_file = self._create_user_file(request, card_cover_upload)

        header_cover_upload = form.cleaned_data.get("header_cover_upload")
        if header_cover_upload:
            obj.header_cover_file = self._create_user_file(request, header_cover_upload)

        super().save_model(request, obj, form, change)


@admin.register(CourseModule)
class CourseModuleAdmin(admin.ModelAdmin):
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
    cdn = CDN(storage=SelectelSwiftStorage())

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
            {
                "fields": (
                    "avatar_file",
                    "avatar_upload",
                )
            },
        ),
        (
            "Системные поля",
            {
                "fields": (
                    "datetime_created",
                    "datetime_updated",
                )
            },
        ),
    )

    def _create_user_file(self, request, uploaded_file):
        info = self.cdn.upload(uploaded_file, request.user, quality=100)
        return UserFile.objects.create(
            link=info.url,
            user=request.user,
            name=info.name,
            size=info.size,
            extension=info.extension,
            mime_type=info.mime_type,
        )

    def save_model(self, request, obj, form, change):
        avatar_upload = form.cleaned_data.get("avatar_upload")
        if avatar_upload:
            obj.avatar_file = self._create_user_file(request, avatar_upload)
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
class CourseTaskAdmin(admin.ModelAdmin):
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
    cdn = CDN(storage=SelectelSwiftStorage())

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
            {
                "fields": (
                    "datetime_created",
                    "datetime_updated",
                )
            },
        ),
    )

    def _create_user_file(self, request, uploaded_file):
        info = self.cdn.upload(uploaded_file, request.user, quality=100)
        return UserFile.objects.create(
            link=info.url,
            user=request.user,
            name=info.name,
            size=info.size,
            extension=info.extension,
            mime_type=info.mime_type,
        )

    def save_model(self, request, obj, form, change):
        image_upload = form.cleaned_data.get("image_upload")
        if image_upload:
            obj.image_file = self._create_user_file(request, image_upload)

        attachment_upload = form.cleaned_data.get("attachment_upload")
        if attachment_upload:
            obj.attachment_file = self._create_user_file(request, attachment_upload)

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
