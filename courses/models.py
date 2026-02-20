from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from files.models import UserFile
from partner_programs.models import PartnerProgram


class CourseAccessType(models.TextChoices):
    ALL_USERS = "all_users", "Для всех пользователей"
    PROGRAM_MEMBERS = "program_members", "Для участников программы"
    SUBSCRIPTION_STUB = "subscription_stub", "По подписке"


class CourseContentStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    PUBLISHED = "published", "Опубликован"
    COMPLETED = "completed", "Завершен"


class Course(models.Model):
    title = models.CharField(
        max_length=45,
        verbose_name="Название курса",
    )
    description = models.TextField(
        blank=True,
        default="",
        validators=[MaxLengthValidator(600)],
        verbose_name="Описание",
    )
    access_type = models.CharField(
        max_length=32,
        choices=CourseAccessType.choices,
        default=CourseAccessType.ALL_USERS,
        verbose_name="Тип доступа",
    )
    partner_program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="courses",
        verbose_name="Программа",
    )
    avatar_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_avatars",
        verbose_name="Аватар курса",
    )
    card_cover_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_card_covers",
        verbose_name="Обложка карточки курса",
    )
    header_cover_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_header_covers",
        verbose_name="Обложка шапки курса",
    )
    start_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Дата старта",
    )
    end_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Дата окончания",
    )
    status = models.CharField(
        max_length=16,
        choices=CourseContentStatus.choices,
        default=CourseContentStatus.DRAFT,
        verbose_name="Статус курса",
    )
    is_completed = models.BooleanField(
        default=False,
        verbose_name="Курс завершен",
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

    class Meta:
        verbose_name = "Курс"
        verbose_name_plural = "Курсы"
        ordering = ("-datetime_created",)
        constraints = [
            models.CheckConstraint(
                check=~Q(access_type=CourseAccessType.PROGRAM_MEMBERS)
                | Q(partner_program__isnull=False),
                name="courses_program_members_requires_program",
            ),
            models.CheckConstraint(
                check=(
                    Q(start_date__isnull=True, end_date__isnull=True)
                    | Q(start_date__isnull=False, end_date__isnull=False)
                ),
                name="courses_dates_must_be_set_together",
            ),
            models.CheckConstraint(
                check=Q(start_date__isnull=True) | Q(end_date__gte=F("start_date")),
                name="courses_end_date_gte_start_date",
            ),
            models.CheckConstraint(
                check=~Q(status=CourseContentStatus.COMPLETED)
                | Q(is_completed=True),
                name="courses_completed_status_implies_flag",
            ),
            models.CheckConstraint(
                check=Q(is_completed=False)
                | Q(status=CourseContentStatus.COMPLETED),
                name="courses_completed_flag_implies_status",
            ),
        ]

    def __str__(self):
        return f"Course<{self.id}> - {self.title}"

    def is_completed_by_date(self) -> bool:
        if not self.end_date:
            return False
        return timezone.localdate() > self.end_date

    def clean(self):
        super().clean()

        if (
            self.access_type == CourseAccessType.PROGRAM_MEMBERS
            and self.partner_program_id is None
        ):
            raise ValidationError(
                {"partner_program": "Поле обязательно для доступа участникам программы."}
            )

        has_start_date = self.start_date is not None
        has_end_date = self.end_date is not None
        if has_start_date != has_end_date:
            raise ValidationError(
                {
                    "start_date": "Дата старта и дата окончания должны быть заполнены вместе.",
                    "end_date": "Дата старта и дата окончания должны быть заполнены вместе.",
                }
            )

        if has_start_date and has_end_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "Дата окончания не может быть раньше даты старта."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()

        if self.status == CourseContentStatus.COMPLETED:
            self.is_completed = True
            if not self.completed_at:
                self.completed_at = timezone.now()

        if self.is_completed and self.status != CourseContentStatus.COMPLETED:
            self.status = CourseContentStatus.COMPLETED
            if not self.completed_at:
                self.completed_at = timezone.now()

        super().save(*args, **kwargs)
