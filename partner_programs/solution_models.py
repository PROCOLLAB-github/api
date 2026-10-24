"""Решение владеет составом, приглашениями и ответами без Project или Team."""

from django.conf import settings
from django.db import models


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


class ProgramSolutionMember(models.Model):
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


class SolutionInvitation(models.Model):
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


class ProgramSolutionAnswer(models.Model):
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
