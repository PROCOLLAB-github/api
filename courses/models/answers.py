from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from files.models import UserFile

from .choices import (
    CourseTaskAnswerType,
    CourseTaskCheckType,
    CourseTaskKind,
    UserTaskAnswerStatus,
)
from .constants import DEFAULT_MAX_FILES_PER_ANSWER
from .content import CourseTask, CourseTaskOption


class UserTaskAnswer(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_task_answers",
        verbose_name="Пользователь",
    )
    task = models.ForeignKey(
        CourseTask,
        on_delete=models.CASCADE,
        related_name="user_answers",
        verbose_name="Задание",
    )
    status = models.CharField(
        max_length=20,
        choices=UserTaskAnswerStatus.choices,
        default=UserTaskAnswerStatus.SUBMITTED,
        verbose_name="Статус ответа",
    )
    answer_text = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        verbose_name="Текст ответа",
    )
    is_correct = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="Ответ корректен",
    )
    submitted_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="Дата и время отправки",
    )
    review_comment = models.TextField(
        blank=True,
        default="",
        verbose_name="Комментарий проверяющего",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_course_task_answers",
        verbose_name="Проверил",
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата и время проверки",
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
        verbose_name = "Ответ пользователя на задание"
        verbose_name_plural = "Ответы пользователей на задания"
        ordering = ("-submitted_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "task"),
                name="courses_user_task_answer_unique_user_task",
            ),
        ]

    def __str__(self):
        return f"UserTaskAnswer<{self.id}> - user={self.user_id} task={self.task_id}"

    def clean(self):
        super().clean()
        errors = {}
        if self.task_id is None:
            return

        if self.task.task_kind != CourseTaskKind.QUESTION:
            errors["task"] = "Ответ можно отправлять только на вопросное задание."

        answer_type = self.task.answer_type
        is_text_filled = CourseTask._require_non_blank(self.answer_text)
        if answer_type in (
            CourseTaskAnswerType.TEXT,
            CourseTaskAnswerType.TEXT_AND_FILES,
        ) and not is_text_filled:
            errors["answer_text"] = "Для выбранного типа ответа требуется заполнить текст."

        if answer_type in (
            CourseTaskAnswerType.SINGLE_CHOICE,
            CourseTaskAnswerType.MULTIPLE_CHOICE,
            CourseTaskAnswerType.FILES,
        ) and is_text_filled:
            errors["answer_text"] = "Для выбранного типа ответа текст не используется."

        if (
            self.task.check_type == CourseTaskCheckType.WITHOUT_REVIEW
            and self.status == UserTaskAnswerStatus.PENDING_REVIEW
        ):
            errors["status"] = "Для заданий без проверки статус pending_review недопустим."

        if bool(self.reviewed_by_id) != bool(self.reviewed_at):
            errors["reviewed_by"] = "Поля reviewed_by и reviewed_at должны быть заполнены вместе."
            errors["reviewed_at"] = "Поля reviewed_by и reviewed_at должны быть заполнены вместе."

        if (
            self.task.check_type == CourseTaskCheckType.WITH_REVIEW
            and self.status in (UserTaskAnswerStatus.ACCEPTED, UserTaskAnswerStatus.REJECTED)
            and not self.reviewed_by_id
        ):
            errors["reviewed_by"] = "Для проверенного ответа укажите проверяющего."
            errors["reviewed_at"] = "Для проверенного ответа укажите время проверки."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        validate = kwargs.pop("validate", True)
        if validate:
            self.full_clean()
        super().save(*args, **kwargs)


class UserTaskAnswerOption(models.Model):
    answer = models.ForeignKey(
        UserTaskAnswer,
        on_delete=models.CASCADE,
        related_name="selected_options",
        verbose_name="Ответ пользователя",
    )
    option = models.ForeignKey(
        CourseTaskOption,
        on_delete=models.CASCADE,
        related_name="selected_in_answers",
        verbose_name="Выбранный вариант",
    )

    class Meta:
        verbose_name = "Выбранный вариант ответа"
        verbose_name_plural = "Выбранные варианты ответа"
        constraints = [
            models.UniqueConstraint(
                fields=("answer", "option"),
                name="courses_user_task_answer_option_unique_answer_option",
            ),
        ]

    def __str__(self):
        return (
            f"UserTaskAnswerOption<{self.id}> "
            f"- answer={self.answer_id} option={self.option_id}"
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.answer_id is None or self.option_id is None:
            return

        if self.answer.task_id != self.option.task_id:
            errors["option"] = (
                "Выбранный вариант должен относиться к тому же заданию, "
                "что и ответ пользователя."
            )

        if self.answer.task.answer_type not in (
            CourseTaskAnswerType.SINGLE_CHOICE,
            CourseTaskAnswerType.MULTIPLE_CHOICE,
        ):
            errors["answer"] = (
                "Выбор варианта доступен только для типов ответа "
                "'single_choice' и 'multiple_choice'."
            )

        if (
            self.answer.task.answer_type == CourseTaskAnswerType.SINGLE_CHOICE
            and UserTaskAnswerOption.objects.filter(answer_id=self.answer_id)
            .exclude(pk=self.pk)
            .exists()
        ):
            errors["answer"] = "Для single_choice можно выбрать только один вариант."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.answer_id:
                # Serializes single_choice writes for one answer.
                self.answer.__class__.objects.select_for_update().get(pk=self.answer_id)
            self.full_clean()
            super().save(*args, **kwargs)


class UserTaskAnswerFile(models.Model):
    answer = models.ForeignKey(
        UserTaskAnswer,
        on_delete=models.CASCADE,
        related_name="files",
        verbose_name="Ответ пользователя",
    )
    file = models.ForeignKey(
        UserFile,
        on_delete=models.CASCADE,
        related_name="course_task_answer_files",
        verbose_name="Файл",
    )
    file_name = models.TextField(
        blank=True,
        default="",
        verbose_name="Название файла",
    )
    file_size = models.PositiveBigIntegerField(
        default=0,
        verbose_name="Размер файла",
    )
    datetime_uploaded = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата загрузки",
    )

    class Meta:
        verbose_name = "Файл ответа пользователя"
        verbose_name_plural = "Файлы ответов пользователей"
        ordering = ("-datetime_uploaded", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("answer", "file"),
                name="courses_user_task_answer_file_unique_answer_file",
            ),
        ]

    def __str__(self):
        return f"UserTaskAnswerFile<{self.id}> - answer={self.answer_id}"

    def clean(self):
        super().clean()
        errors = {}
        if self.answer_id is None:
            return

        answer_type = self.answer.task.answer_type
        if answer_type not in (
            CourseTaskAnswerType.FILES,
            CourseTaskAnswerType.TEXT_AND_FILES,
        ):
            errors["answer"] = (
                "Загрузка файлов доступна только для типов ответа "
                "'files' и 'text_and_files'."
            )

        existing_count = (
            UserTaskAnswerFile.objects.filter(answer_id=self.answer_id)
            .exclude(pk=self.pk)
            .count()
        )
        if existing_count >= DEFAULT_MAX_FILES_PER_ANSWER:
            errors["answer"] = (
                f"Превышен лимит файлов в ответе ({DEFAULT_MAX_FILES_PER_ANSWER})."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.file_id:
            if not self.file_name:
                self.file_name = self.file.name
            if self.file_size == 0:
                self.file_size = self.file.size
        self.full_clean()
        super().save(*args, **kwargs)
