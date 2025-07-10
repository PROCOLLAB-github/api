from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django_stubs_ext.db.models import TypedModelMeta

from files.models import UserFile
from projects.models import Project
from vacancy.constants import WorkExperience, WorkFormat, WorkSchedule
from vacancy.managers import VacancyManager, VacancyResponseManager


class Vacancy(models.Model):
    """
    Vacancy model

    Attributes:
        role: A CharField title of the vacancy.
        required_skills: A GenericRelation of required skills for the vacancy.
        description: A TextField description of the vacancy.
        required_experience: CharField (choice).
        work_schedule: CharField (choice).
        work_format: CharField (choice).
        project: A ForeignKey referring to the Company model.
        is_active: A boolean indicating if Vacancy is active.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    role = models.CharField(max_length=256, null=False)
    specialization = models.CharField(
        max_length=128, null=True, blank=True, verbose_name="Специализация"
    )
    required_skills = GenericRelation(
        "core.SkillToObject",
        related_query_name="vacancies",
    )
    description = models.TextField(blank=True)
    required_experience = models.CharField(
        max_length=50,
        choices=WorkExperience.choices(),
        blank=True,
        null=True,
        verbose_name="Требуемый опыт",
    )
    work_schedule = models.CharField(
        max_length=50,
        choices=WorkSchedule.choices(),
        blank=True,
        null=True,
        verbose_name="График работы",
    )
    work_format = models.CharField(
        max_length=50,
        choices=WorkFormat.choices(),
        blank=True,
        null=True,
        verbose_name="Формат работы",
    )
    salary = models.IntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
        verbose_name="Зарплата",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=False,
        related_name="vacancies",
    )
    datetime_created = models.DateTimeField(
        null=False,
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        null=False,
        auto_now=True,
        verbose_name="Дата обновления",
    )
    datetime_closed = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата закрытия",
    )
    is_active = models.BooleanField(blank=False, default=True)

    objects = VacancyManager()

    def get_required_skills(self):
        required_skills = []
        for sto in self.required_skills.all():
            required_skills.append(sto.skill)
        return required_skills

    def update_datetime_closed(self):
        """Update datetime_closed based on the is_active status."""
        if not self.is_active and self.datetime_closed is None:
            self.datetime_closed = timezone.now()
        elif self.is_active:
            self.datetime_closed = None

    def save(self, *args, **kwargs):
        self.update_datetime_closed()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Vacancy<{self.id}> - {self.role}"

    class Meta(TypedModelMeta):
        verbose_name = "Вакансия"
        verbose_name_plural = "Вакансии"
        ordering = ["-datetime_created"]


class VacancyResponse(models.Model):
    """
    VacancyResponse model

    Attributes:
        user: A ForeignKey referring to the User model.
        vacancy: A ForeignKey referring to the Vacancy model.
        is_approved: A boolean indicating if VacancyResponse is approved.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
        accompanying_file: A OneToOneField to UserFile.
    """

    user = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        null=False,
        related_name="vacancy_requests",
    )
    vacancy = models.ForeignKey(
        Vacancy,
        on_delete=models.CASCADE,
        null=False,
        related_name="vacancy_requests",
    )
    why_me = models.TextField(blank=True)
    accompanying_file = models.OneToOneField(
        UserFile,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="vacancy_file",
        verbose_name="Сопроводительный файл",
    )

    is_approved = models.BooleanField(
        blank=True,
        null=True,
    )

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата обновления", null=False, auto_now=True
    )

    objects = VacancyResponseManager()

    def __str__(self) -> str:
        return f"VacancyResponse<{self.id}> - {self.user} - {self.vacancy}"

    class Meta(TypedModelMeta):
        verbose_name = "Отклик на вакансию"
        verbose_name_plural = "Отклик на вакансии"
        ordering = ["-datetime_created"]
