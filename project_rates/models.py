from django.contrib.auth import get_user_model
from django.db import models
from .constants import VERBOSE_TYPES

from partner_programs.models import PartnerProgram
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
    type = models.CharField(  # noqa A003 VNE003
        verbose_name="Тип", max_length=8, choices=VERBOSE_TYPES
    )

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
