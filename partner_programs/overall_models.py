"""Окончательный нормализованный результат одного квиза команды в программе."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from project_rates.scoring import decimal_number


def normalized_stage_score(value):
    try:
        number = decimal_number(value)
        if not 0 <= number <= 100 or number != number.quantize(Decimal("0.01")):
            raise ValueError()
        return number.quantize(Decimal("0.01"))
    except (ValueError, ArithmeticError) as error:
        raise ValidationError(
            "Укажите балл этапа от 0 до 100, до двух знаков после запятой."
        ) from error


class QuizOutcomeQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Завершенный результат квиза нельзя изменять.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Завершенный результат квиза нельзя изменять.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError(
            "Используйте серверную запись результата завершенной попытки."
        )


class ProgramQuizOutcome(models.Model):
    program = models.ForeignKey(
        "partner_programs.PartnerProgram",
        on_delete=models.CASCADE,
        related_name="quiz_outcomes",
        verbose_name="Программа",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="quiz_outcomes",
        verbose_name="Команда (проект)",
    )
    source_attempt_id = models.CharField(
        max_length=128,
        unique=True,
        verbose_name="Идентификатор завершенной попытки",
    )
    score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name="Балл квиза из 100",
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    recorded_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Результат получен"
    )
    objects = QuizOutcomeQuerySet.as_manager()

    class Meta:
        verbose_name = "Результат командного квиза"
        verbose_name_plural = "Результаты командных квизов"
        constraints = [
            models.UniqueConstraint(
                fields=("program", "project"), name="quiz_outcome_one_per_team"
            ),
            models.CheckConstraint(
                condition=models.Q(score__gte=0, score__lte=100),
                name="quiz_outcome_score_0_100",
            ),
        ]

    def __str__(self):
        return f"{self.program} / {self.project}: {self.score}"

    def clean(self):
        super().clean()
        self.score = normalized_stage_score(self.score)
        if (
            not self.source_attempt_id
            or self.source_attempt_id != self.source_attempt_id.strip()
        ):
            raise ValidationError(
                {
                    "source_attempt_id": "Укажите непустой идентификатор без пробелов по краям."
                }
            )
        if not self.pk:
            from partner_programs.models import PartnerProgramProject

            if not PartnerProgramProject.objects.filter(
                partner_program_id=self.program_id,
                project_id=self.project_id,
            ).exists():
                raise ValidationError("Команда не зарегистрирована в этой программе.")
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous and any(
                getattr(previous, name) != getattr(self, name)
                for name in (
                    "program_id",
                    "project_id",
                    "source_attempt_id",
                    "score",
                    "recorded_at",
                )
            ):
                raise ValidationError("Завершенный результат квиза нельзя изменять.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
