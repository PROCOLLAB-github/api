from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from projects.models import Project
from vacancy.managers import VacancyManager, VacancyResponseManager


class Vacancy(models.Model):
    """
    Vacancy model

    Attributes:
        role: A CharField title of the vacancy.
        required_skills_old: A CharField required skills for the vacancy (to be deprecated).
        required_skills: A GenericRelation of required skills for the vacancy.
        description: A TextField description of the vacancy.
        project: A ForeignKey referring to the Company model.
        is_active: A boolean indicating if Vacancy is active.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    role = models.CharField(max_length=256, null=False)
    required_skills_old = models.TextField(blank=True)  # to be deprecated in future
    required_skills = GenericRelation(
        "core.SkillToObject",
        related_query_name="vacancies",
    )
    description = models.TextField(blank=True)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=False,
        related_name="vacancies",
    )

    is_active = models.BooleanField(blank=False, default=True)

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата обновления", null=False, auto_now=True
    )

    objects = VacancyManager()

    def get_required_skills(self):
        required_skills = []
        for sto in self.required_skills.all():
            required_skills.append(sto.skill)
        return required_skills

    def __str__(self):
        return f"Vacancy<{self.id}> - {self.role}"

    class Meta:
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

    def __str__(self):
        return f"VacancyResponse<{self.id}> - {self.user} - {self.vacancy}"

    class Meta:
        verbose_name = "Отклик на вакансию"
        verbose_name_plural = "Отклик на вакансии"
        ordering = ["-datetime_created"]
