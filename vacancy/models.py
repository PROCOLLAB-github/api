from django.db import models

from projects.models import Project


class Vacancy(models.Model):
    """
    Vacancy model

    Attributes:
        role: A CharField title of the vacancy.
        required_skills: A CharField required skills for the vacancy.
        description: A TextField description of the vacancy.
        project: A ForeignKey referring to the Company model.
        is_active: A boolean indicating if Vacancy is active.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    role = models.CharField(max_length=256, null=False)
    required_skills = models.TextField(blank=True)
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

    def __str__(self):
        return self.role

    class Meta:
        verbose_name = "Вакансия"
        verbose_name_plural = "Вакансии"
        ordering = ["-datetime_created"]


class VacancyRequest(models.Model):
    """
    VacancyRequest model

    Attributes:
        user: A ForeignKey referring to the User model.
        vacancy: A ForeignKey referring to the Vacancy model.
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

    is_approve = models.BooleanField(blank=True)

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата обновления", null=False, auto_now=True
    )

    def __str__(self):
        return f"VacancyRequest<{self.id}> - {self.user} - {self.vacancy}"

    class Meta:
        verbose_name = "Заявка на вакансию"
        verbose_name_plural = "Заявки на вакансии"
        ordering = ["-datetime_created"]
