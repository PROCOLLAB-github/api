"""Решение владеет составом, приглашениями и ответами без Project или Team."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


class ProgramSolution(models.Model):
    program = models.ForeignKey(
        "partner_programs.PartnerProgram",
        on_delete=models.CASCADE,
        related_name="solutions",
    )
    captain = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=256, default="Новое решение")
    version = models.PositiveBigIntegerField(default=1)
    status = models.CharField(
        max_length=12,
        default="draft",
        choices=[("draft", "Черновик"), ("submitted", "Сдано")],
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    submission_snapshot = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @transaction.atomic
    def save(self, *args, **kwargs):
        previous = lock_saved_solution(self.pk) if self.pk else None
        if previous:
            if previous.program_id != self.program_id:
                raise ValidationError(
                    "Решение нельзя переназначить другой программе.",
                    code="invalid_program_context",
                )
            selected = kwargs.get("update_fields")
            frozen_fields = (
                "program",
                "captain",
                "name",
                "status",
                "submitted_at",
                "submission_snapshot",
            )
            if previous.status == "submitted" and any(
                (selected is None or field in selected or field + "_id" in selected)
                and getattr(
                    previous, field + "_id" if field in ("program", "captain") else field
                )
                != getattr(
                    self, field + "_id" if field in ("program", "captain") else field
                )
                for field in frozen_fields
            ):
                raise ValidationError(
                    "Сданное решение нельзя изменять или возвращать в черновик.",
                    code="team_frozen",
                )
        return super().save(*args, **kwargs)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "captain"],
                name="unique_solution_program_captain",
            ),
            models.CheckConstraint(
                check=models.Q(version__gte=1), name="solution_version_positive"
            ),
            models.CheckConstraint(
                check=(
                    models.Q(
                        status="draft",
                        submitted_at__isnull=True,
                        submission_snapshot__isnull=True,
                    )
                    | models.Q(
                        status="submitted",
                        submitted_at__isnull=False,
                        submission_snapshot__isnull=False,
                    )
                ),
                name="solution_submission_consistent",
            ),
        ]


class SolutionOwnedRecord(models.Model):
    """Обычные model/admin записи используют ту же сериализацию, что и API."""

    class Meta:
        abstract = True

    @transaction.atomic
    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if previous and previous.solution_id != self.solution_id:
            raise ValidationError(
                "Запись нельзя переносить в другую заявку.",
                code="invalid_program_context",
            )
        solution = lock_saved_solution(self.solution_id) if self.solution_id else None
        # Другой writer мог обработать запись, пока мы ожидали блокировку программы.
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if (
            solution
            and solution.status == "submitted"
            and not self.allowed_after_submission(previous, kwargs.get("update_fields"))
        ):
            raise ValidationError(
                "Данные и состав сданного решения зафиксированы.", code="team_frozen"
            )
        return super().save(*args, **kwargs)

    def allowed_after_submission(self, previous, selected):
        return False


class ProgramSolutionMember(SolutionOwnedRecord):
    solution = models.ForeignKey(
        ProgramSolution, on_delete=models.CASCADE, related_name="members"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=128, null=True, blank=True)
    specialization = models.CharField(max_length=100, null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["joined_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["solution", "user"], name="unique_solution_member"
            )
        ]


class SolutionInvitation(SolutionOwnedRecord):
    solution = models.ForeignKey(
        ProgramSolution, on_delete=models.CASCADE, related_name="invitations"
    )
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=128, null=True, blank=True)
    specialization = models.CharField(max_length=100, null=True, blank=True)
    motivational_letter = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=12,
        default="pending",
        choices=[
            ("pending", "Ожидает ответа"),
            ("accepted", "Принято"),
            ("declined", "Отклонено"),
        ],
    )
    version = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def allowed_after_submission(self, previous, selected):
        # Pending может быть отклонен; принятие, создание и изменение роли закрыты.
        return (
            previous is not None
            and previous.status == "pending"
            and self.status == "declined"
            and all(
                (
                    selected is not None
                    and field not in selected
                    and field.removesuffix("_id") not in selected
                )
                or getattr(previous, field) == getattr(self, field)
                for field in (
                    "recipient_id",
                    "role",
                    "specialization",
                    "motivational_letter",
                )
            )
        )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["solution", "recipient"],
                condition=models.Q(status="pending"),
                name="unique_pending_solution_invite",
            ),
            models.CheckConstraint(
                check=models.Q(version__gte=1), name="solution_invite_version_positive"
            ),
            models.CheckConstraint(
                check=models.Q(status__in=["pending", "accepted", "declined"]),
                name="solution_invite_status_valid",
            ),
        ]


class ProgramSolutionAnswer(SolutionOwnedRecord):
    solution = models.ForeignKey(
        ProgramSolution, on_delete=models.CASCADE, related_name="answers"
    )
    field = models.ForeignKey(
        "partner_programs.PartnerProgramField",
        on_delete=models.PROTECT,
        related_name="solution_answers",
    )
    value = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["solution", "field"], name="unique_solution_answer"
            )
        ]


def lock_saved_solution(solution_id):
    """Вызывается только внутри atomic: программа -> решение, как у команд API."""
    reference = (
        ProgramSolution.objects.filter(pk=solution_id)
        .values_list("program_id", flat=True)
        .first()
    )
    if reference is None:
        return None
    from partner_programs.models import PartnerProgram

    PartnerProgram.objects.select_for_update().get(pk=reference)
    return ProgramSolution.objects.select_for_update().filter(pk=solution_id).first()
