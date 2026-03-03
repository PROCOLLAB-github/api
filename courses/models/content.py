from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from files.models import UserFile

from .choices import (
    CourseLessonContentStatus,
    CourseModuleContentStatus,
    CourseTaskAnswerType,
    CourseTaskCheckType,
    CourseTaskContentStatus,
    CourseTaskInformationalType,
    CourseTaskKind,
    CourseTaskQuestionType,
)
from .course import Course


class CourseModule(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="modules",
        verbose_name="Курс",
    )
    title = models.CharField(
        max_length=40,
        verbose_name="Название модуля",
    )
    avatar_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_module_avatars",
        verbose_name="Аватар модуля",
    )
    start_date = models.DateField(
        verbose_name="Дата старта модуля",
    )
    status = models.CharField(
        max_length=16,
        choices=CourseModuleContentStatus.choices,
        default=CourseModuleContentStatus.DRAFT,
        verbose_name="Статус модуля",
    )
    order = models.PositiveIntegerField(
        default=1,
        verbose_name="Порядковый номер",
    )
    datetime_created = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Модуль курса"
        verbose_name_plural = "Модули курса"
        ordering = ("course_id", "order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("course", "order"),
                name="courses_module_unique_course_order",
            ),
            models.CheckConstraint(
                check=Q(order__gte=1),
                name="courses_module_order_gte_1",
            ),
        ]

    def __str__(self):
        return f"CourseModule<{self.id}> - {self.title}"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class CourseLesson(models.Model):
    module = models.ForeignKey(
        CourseModule,
        on_delete=models.CASCADE,
        related_name="lessons",
        verbose_name="Модуль курса",
    )
    title = models.CharField(
        max_length=45,
        verbose_name="Название урока",
    )
    status = models.CharField(
        max_length=16,
        choices=CourseLessonContentStatus.choices,
        default=CourseLessonContentStatus.DRAFT,
        verbose_name="Статус урока",
    )
    order = models.PositiveIntegerField(
        default=1,
        verbose_name="Порядковый номер",
    )
    datetime_created = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Урок курса"
        verbose_name_plural = "Уроки курса"
        ordering = ("module_id", "order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("module", "order"),
                name="courses_lesson_unique_module_order",
            ),
            models.CheckConstraint(
                check=Q(order__gte=1),
                name="courses_lesson_order_gte_1",
            ),
        ]

    def __str__(self):
        return f"CourseLesson<{self.id}> - {self.title}"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class CourseTask(models.Model):
    lesson = models.ForeignKey(
        CourseLesson,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="Урок курса",
    )
    title = models.CharField(
        max_length=255,
        verbose_name="Название задания",
    )
    body_text = models.TextField(
        blank=True,
        default="",
        verbose_name="Текст",
    )
    status = models.CharField(
        max_length=16,
        choices=CourseTaskContentStatus.choices,
        default=CourseTaskContentStatus.DRAFT,
        verbose_name="Статус задания",
    )
    task_kind = models.CharField(
        max_length=16,
        choices=CourseTaskKind.choices,
        verbose_name="Тип задания",
    )
    check_type = models.CharField(
        max_length=16,
        choices=CourseTaskCheckType.choices,
        null=True,
        blank=True,
        verbose_name="Тип проверки",
    )
    informational_type = models.CharField(
        max_length=24,
        choices=CourseTaskInformationalType.choices,
        null=True,
        blank=True,
        verbose_name="Тип информационного задания",
    )
    question_type = models.CharField(
        max_length=24,
        choices=CourseTaskQuestionType.choices,
        null=True,
        blank=True,
        verbose_name="Тип вопроса",
    )
    answer_type = models.CharField(
        max_length=24,
        choices=CourseTaskAnswerType.choices,
        null=True,
        blank=True,
        verbose_name="Тип ответа",
    )
    video_url = models.URLField(
        null=True,
        blank=True,
        verbose_name="Ссылка на видео",
    )
    image_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_task_images",
        verbose_name="Изображение",
    )
    attachment_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_task_attachments",
        verbose_name="Файл",
    )
    order = models.PositiveIntegerField(
        default=1,
        verbose_name="Порядковый номер",
    )
    datetime_created = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Задание курса"
        verbose_name_plural = "Задания курса"
        ordering = ("lesson_id", "order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("lesson", "order"),
                name="courses_task_unique_lesson_order",
            ),
            models.CheckConstraint(
                check=Q(order__gte=1),
                name="courses_task_order_gte_1",
            ),
            models.CheckConstraint(
                check=~Q(task_kind=CourseTaskKind.INFORMATIONAL)
                | Q(informational_type__isnull=False),
                name="courses_task_info_requires_info_type",
            ),
            models.CheckConstraint(
                check=~Q(task_kind=CourseTaskKind.QUESTION)
                | (
                    Q(question_type__isnull=False)
                    & Q(answer_type__isnull=False)
                    & Q(check_type__isnull=False)
                ),
                name="courses_task_question_requires_types",
            ),
            models.CheckConstraint(
                check=~Q(task_kind=CourseTaskKind.INFORMATIONAL)
                | (
                    Q(question_type__isnull=True)
                    & Q(answer_type__isnull=True)
                    & Q(check_type__isnull=True)
                ),
                name="courses_task_info_forbids_question_fields",
            ),
            models.CheckConstraint(
                check=~Q(task_kind=CourseTaskKind.QUESTION)
                | Q(informational_type__isnull=True),
                name="courses_task_question_forbids_info_type",
            ),
        ]

    def __str__(self):
        return f"CourseTask<{self.id}> - {self.title}"

    @staticmethod
    def _require_non_blank(value: str | None) -> bool:
        return bool(value and value.strip())

    def clean(self):
        super().clean()

        errors = {}

        if self.task_kind == CourseTaskKind.INFORMATIONAL:
            if self.informational_type == CourseTaskInformationalType.VIDEO_TEXT:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = "Поле обязательно для типа 'Видео и текст'."
                if not self._require_non_blank(self.video_url):
                    errors["video_url"] = "Поле обязательно для типа 'Видео и текст'."
            elif self.informational_type == CourseTaskInformationalType.TEXT:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = "Поле обязательно для типа 'Текст'."
            elif self.informational_type == CourseTaskInformationalType.TEXT_IMAGE:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = (
                        "Поле обязательно для типа 'Текст и изображение'."
                    )
                if self.image_file_id is None:
                    errors["image_file"] = (
                        "Поле обязательно для типа 'Текст и изображение'."
                    )

        if self.task_kind == CourseTaskKind.QUESTION:
            if self.question_type == CourseTaskQuestionType.IMAGE_TEXT:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = (
                        "Поле обязательно для типа вопроса 'Изображение и текст'."
                    )
                if self.image_file_id is None:
                    errors["image_file"] = (
                        "Поле обязательно для типа вопроса 'Изображение и текст'."
                    )
            elif self.question_type == CourseTaskQuestionType.VIDEO:
                if not self._require_non_blank(self.video_url):
                    errors["video_url"] = "Поле обязательно для типа вопроса 'Видео'."
            elif self.question_type == CourseTaskQuestionType.IMAGE:
                if self.image_file_id is None:
                    errors["image_file"] = (
                        "Поле обязательно для типа вопроса 'Изображение'."
                    )
            elif self.question_type == CourseTaskQuestionType.TEXT_FILE:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = (
                        "Поле обязательно для типа вопроса 'Текст с файлом'."
                    )
                if self.attachment_file_id is None:
                    errors["attachment_file"] = (
                        "Поле обязательно для типа вопроса 'Текст с файлом'."
                    )
            elif self.question_type == CourseTaskQuestionType.TEXT:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = "Поле обязательно для типа вопроса 'Текст'."

        if (
            self.status == CourseTaskContentStatus.PUBLISHED
            and self.task_kind == CourseTaskKind.QUESTION
            and self.answer_type
            in (
                CourseTaskAnswerType.SINGLE_CHOICE,
                CourseTaskAnswerType.MULTIPLE_CHOICE,
            )
        ):
            correct_count = (
                self.options.filter(is_correct=True).count()
                if self.pk
                else 0
            )
            if correct_count == 0:
                errors["status"] = (
                    "Нельзя опубликовать тестовое задание без правильного варианта."
                )
            elif (
                self.answer_type == CourseTaskAnswerType.SINGLE_CHOICE
                and correct_count != 1
            ):
                errors["status"] = (
                    "Для single_choice должен быть ровно один правильный вариант."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class CourseTaskOption(models.Model):
    task = models.ForeignKey(
        CourseTask,
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name="Задание",
    )
    text = models.CharField(
        max_length=500,
        verbose_name="Текст варианта",
    )
    is_correct = models.BooleanField(
        default=False,
        verbose_name="Правильный вариант",
    )
    order = models.PositiveIntegerField(
        default=1,
        verbose_name="Порядковый номер",
    )
    datetime_created = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Вариант ответа задания"
        verbose_name_plural = "Варианты ответов задания"
        ordering = ("task_id", "order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("task", "order"),
                name="courses_task_option_unique_task_order",
            ),
            models.CheckConstraint(
                check=Q(order__gte=1),
                name="courses_task_option_order_gte_1",
            ),
        ]

    def __str__(self):
        return f"CourseTaskOption<{self.id}> - task={self.task_id}"

    def clean(self):
        super().clean()
        errors = {}
        if self.task_id is None:
            return

        if self.task.task_kind != CourseTaskKind.QUESTION:
            errors["task"] = "Варианты ответа допустимы только для вопросных заданий."

        if self.task.answer_type not in (
            CourseTaskAnswerType.SINGLE_CHOICE,
            CourseTaskAnswerType.MULTIPLE_CHOICE,
        ):
            errors["task"] = (
                "Варианты ответа доступны только для типов "
                "'single_choice' и 'multiple_choice'."
            )

        if (
            self.task.answer_type == CourseTaskAnswerType.SINGLE_CHOICE
            and self.is_correct
            and CourseTaskOption.objects.filter(
                task_id=self.task_id,
                is_correct=True,
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            errors["is_correct"] = (
                "Для single_choice может быть только один правильный вариант."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
