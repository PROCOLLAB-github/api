from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from .constants import VERBOSE_TYPES

from partner_programs.models import PartnerProgram, PartnerProgramProject
from projects.models import Project
from .validators import ProjectScoreValidator

User = get_user_model()


class Criteria(models.Model):
    """
    Criteria model

    Attributes:
        name:  A CharField name of the criteria
        description: A TextField description of criteria
        type: A CharField choice between "str", "int", "bool" and "float"
        min_value: Optional FloatField for numeric values
        max_value: Optional FloatField for numeric values
        partner_program: A ForeignKey connection to PartnerProgram model

    """

    name = models.CharField(verbose_name="Название", max_length=50)
    description = models.TextField(verbose_name="Описание", null=True, blank=True)
    type = models.CharField(verbose_name="Тип", max_length=8, choices=VERBOSE_TYPES)

    min_value = models.FloatField(
        verbose_name="Минимально допустимое числовое значение",
        help_text="(если есть)",
        null=True,
        blank=True,
    )
    max_value = models.FloatField(
        verbose_name="Максимально допустимое числовое значение",
        help_text="(если есть)",
        null=True,
        blank=True,
    )
    partner_program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="criterias",
    )

    def __str__(self):
        return f"Criteria<{self.id}> - {self.name} {self.partner_program.name}"

    class Meta:
        verbose_name = "Критерий оценки проекта"
        verbose_name_plural = "Критерии оценки проектов"


class ProjectScore(models.Model):
    """
    ProjectScore model

    Attributes:
        criteria:  A ForeignKey connection to Criteria model
        user:  A ForeignKey connection to User model

        value: CharField for value


    """

    criteria = models.ForeignKey(
        Criteria, on_delete=models.CASCADE, related_name="scores"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scores")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="scores")

    value = models.CharField(
        verbose_name="Значение", max_length=50, null=True, blank=True
    )

    def __str__(self):
        return f"ProjectScore<{self.id}> - {self.criteria.name}"

    def save(self, *args, **kwargs):
        data_to_validate = {
            "criteria_type": self.criteria.type,
            "value": self.value,
            "criteria_min_value": self.criteria.min_value,
            "criteria_max_value": self.criteria.max_value,
        }
        ProjectScoreValidator.validate(**data_to_validate)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Оценка проекта"
        verbose_name_plural = "Оценки проектов"
        unique_together = ("criteria", "user", "project")


class ProjectExpertAssignment(models.Model):
    partner_program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="project_expert_assignments",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="expert_assignments",
    )
    expert = models.ForeignKey(
        "users.Expert",
        on_delete=models.CASCADE,
        related_name="project_assignments",
    )
    datetime_created = models.DateTimeField(auto_now_add=True)
    datetime_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Назначение проекта эксперту"
        verbose_name_plural = "Назначения проектов экспертам"
        unique_together = ("partner_program", "project", "expert")
        indexes = [
            models.Index(fields=["partner_program", "project"]),
            models.Index(fields=["partner_program", "expert"]),
        ]

    def __str__(self):
        return (
            f"Assignment<{self.id}> program={self.partner_program_id} "
            f"project={self.project_id} expert={self.expert_id}"
        )

    def has_scores(self) -> bool:
        return ProjectScore.objects.filter(
            project_id=self.project_id,
            user_id=self.expert.user_id,
            criteria__partner_program_id=self.partner_program_id,
        ).exists()

    def clean(self):
        errors = {}

        if self.expert_id and self.partner_program_id and not self.expert.programs.filter(
            id=self.partner_program_id
        ).exists():
            errors["expert"] = "Эксперт не состоит в указанной программе."

        if self.project_id and self.partner_program_id and not PartnerProgramProject.objects.filter(
            partner_program_id=self.partner_program_id,
            project_id=self.project_id,
        ).exists():
            errors["project"] = "Проект не привязан к указанной программе."

        if self.partner_program_id and self.project_id:
            max_rates = self.partner_program.max_project_rates
            if max_rates:
                assignments_qs = ProjectExpertAssignment.objects.filter(
                    partner_program_id=self.partner_program_id,
                    project_id=self.project_id,
                )
                if self.pk:
                    assignments_qs = assignments_qs.exclude(pk=self.pk)
                if assignments_qs.count() >= max_rates:
                    errors["partner_program"] = (
                        "Достигнуто максимальное количество назначенных экспертов "
                        "для этого проекта в программе."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.has_scores():
            raise ValidationError(
                "Нельзя удалить назначение: эксперт уже оценил этот проект."
            )
        return super().delete(*args, **kwargs)
