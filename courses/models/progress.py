from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .choices import ProgressStatus
from .content import CourseLesson, CourseModule, CourseTask
from .course import Course


def _status_percent_check(allow_blocked: bool = False) -> Q:
    check = (
        Q(status=ProgressStatus.NOT_STARTED, percent=0)
        | Q(status=ProgressStatus.IN_PROGRESS, percent__gte=1, percent__lte=99)
        | Q(status=ProgressStatus.COMPLETED, percent=100)
    )
    if allow_blocked:
        check |= Q(status=ProgressStatus.BLOCKED, percent=0)
    return check


class BaseUserProgress(models.Model):
    status = models.CharField(
        max_length=16,
        choices=ProgressStatus.choices,
        default=ProgressStatus.NOT_STARTED,
        verbose_name="Статус прогресса",
    )
    percent = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Прогресс, %",
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата начала",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата завершения",
    )
    datetime_created = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    # blocked допускается только для прогресса урока
    allow_blocked_status = False

    class Meta:
        abstract = True

    def _validate_status_percent(self, errors: dict):
        if self.status == ProgressStatus.NOT_STARTED and self.percent != 0:
            errors["percent"] = "Для статуса not_started прогресс должен быть 0%."

        if self.status == ProgressStatus.IN_PROGRESS and not (0 < self.percent < 100):
            errors["percent"] = "Для статуса in_progress прогресс должен быть от 1% до 99%."

        if self.status == ProgressStatus.COMPLETED and self.percent != 100:
            errors["percent"] = "Для статуса completed прогресс должен быть 100%."

        if self.status == ProgressStatus.BLOCKED:
            if not self.allow_blocked_status:
                errors["status"] = "Статус blocked допустим только для прогресса урока."
            elif self.percent != 0:
                errors["percent"] = "Для статуса blocked прогресс должен быть 0%."

    def clean(self):
        super().clean()
        errors = {}
        self._validate_status_percent(errors)

        if self.completed_at and self.status != ProgressStatus.COMPLETED:
            errors["completed_at"] = "completed_at допустимо только для статуса completed."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        validate = kwargs.pop("validate", True)
        if self.status in (ProgressStatus.IN_PROGRESS, ProgressStatus.COMPLETED) and not self.started_at:
            self.started_at = timezone.now()

        if self.status == ProgressStatus.COMPLETED and not self.completed_at:
            self.completed_at = timezone.now()

        if self.status != ProgressStatus.COMPLETED:
            self.completed_at = None

        if validate:
            self.full_clean()
        super().save(*args, **kwargs)


class UserCourseProgress(BaseUserProgress):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_progresses",
        verbose_name="Пользователь",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="user_progresses",
        verbose_name="Курс",
    )
    last_visit_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата последнего визита",
    )

    class Meta:
        verbose_name = "Прогресс пользователя по курсу"
        verbose_name_plural = "Прогресс пользователей по курсам"
        ordering = ("-datetime_updated", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "course"),
                name="courses_user_course_progress_unique_user_course",
            ),
            models.CheckConstraint(
                check=Q(percent__gte=0) & Q(percent__lte=100),
                name="courses_user_course_progress_percent_0_100",
            ),
            models.CheckConstraint(
                check=~Q(status=ProgressStatus.BLOCKED),
                name="courses_user_course_progress_status_no_blocked",
            ),
            models.CheckConstraint(
                check=_status_percent_check(allow_blocked=False),
                name="courses_user_course_progress_status_percent_valid",
            ),
        ]

    def __str__(self):
        return f"UserCourseProgress<{self.id}> - user={self.user_id} course={self.course_id}"


class UserModuleProgress(BaseUserProgress):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="module_progresses",
        verbose_name="Пользователь",
    )
    module = models.ForeignKey(
        CourseModule,
        on_delete=models.CASCADE,
        related_name="user_progresses",
        verbose_name="Модуль",
    )

    class Meta:
        verbose_name = "Прогресс пользователя по модулю"
        verbose_name_plural = "Прогресс пользователей по модулям"
        ordering = ("-datetime_updated", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "module"),
                name="courses_user_module_progress_unique_user_module",
            ),
            models.CheckConstraint(
                check=Q(percent__gte=0) & Q(percent__lte=100),
                name="courses_user_module_progress_percent_0_100",
            ),
            models.CheckConstraint(
                check=~Q(status=ProgressStatus.BLOCKED),
                name="courses_user_module_progress_status_no_blocked",
            ),
            models.CheckConstraint(
                check=_status_percent_check(allow_blocked=False),
                name="courses_user_module_progress_status_percent_valid",
            ),
        ]

    def __str__(self):
        return f"UserModuleProgress<{self.id}> - user={self.user_id} module={self.module_id}"


class UserLessonProgress(BaseUserProgress):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lesson_progresses",
        verbose_name="Пользователь",
    )
    lesson = models.ForeignKey(
        CourseLesson,
        on_delete=models.CASCADE,
        related_name="user_progresses",
        verbose_name="Урок",
    )
    current_task = models.ForeignKey(
        CourseTask,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_in_lesson_progress",
        verbose_name="Текущее задание",
    )

    allow_blocked_status = True

    class Meta:
        verbose_name = "Прогресс пользователя по уроку"
        verbose_name_plural = "Прогресс пользователей по урокам"
        ordering = ("-datetime_updated", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "lesson"),
                name="courses_user_lesson_progress_unique_user_lesson",
            ),
            models.CheckConstraint(
                check=Q(percent__gte=0) & Q(percent__lte=100),
                name="courses_user_lesson_progress_percent_0_100",
            ),
            models.CheckConstraint(
                check=_status_percent_check(allow_blocked=True),
                name="courses_user_lesson_progress_status_percent_valid",
            ),
        ]

    def __str__(self):
        return f"UserLessonProgress<{self.id}> - user={self.user_id} lesson={self.lesson_id}"

    def clean(self):
        super().clean()
        if self.current_task_id and self.lesson_id and self.current_task.lesson_id != self.lesson_id:
            raise ValidationError(
                {"current_task": "Текущее задание должно принадлежать этому уроку."}
            )

    def save(self, *args, **kwargs):
        if self.status in (ProgressStatus.NOT_STARTED, ProgressStatus.BLOCKED):
            self.current_task = None
        super().save(*args, **kwargs)
