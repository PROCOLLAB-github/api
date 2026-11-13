from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from .constants import VERBOSE_TYPES

from partner_programs.models import PartnerProgram, PartnerProgramProject
from projects.models import Project
from .validators import ProjectScoreValidator

User = get_user_model()


class CriteriaQuerySet(models.QuerySet):
    def delete(self):
        from .criteria_policy import locked
        from .scoring import validate_configuration

        with transaction.atomic():
            selected = list(self.values_list("pk", "partner_program_id"))
            deleted = [pk for pk, _ in selected]
            ids = {program_id for _, program_id in selected}
            programs = list(
                PartnerProgram.objects.select_for_update()
                .filter(pk__in=ids)
                .order_by("pk")
            )
            current = list(
                self.filter(pk__in=deleted).values_list("pk", "partner_program_id")
            )
            if any(program_id not in ids for _, program_id in current):
                raise ValidationError("Критерий изменился. Обновите данные.")
            deleted = [pk for pk, _ in current]
            if any(locked(p) for p in programs):
                raise ValidationError("После первой оценки критерии нельзя удалять.")
            for program in programs:
                validate_configuration(
                    program, list(program.criterias.exclude(pk__in=deleted))
                )
            return models.QuerySet.delete(self.filter(pk__in=deleted))


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
    weight_percent = models.DecimalField(
        verbose_name="Вес, %", max_digits=5, decimal_places=2, null=True, blank=True
    )
    partner_program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="criterias",
    )

    objects = CriteriaQuerySet.as_manager()

    def clean(self):
        super().clean()
        from .scoring import validate_weight

        try:
            validate_weight(self)
        except ValueError as error:
            raise ValidationError({"weight_percent": str(error)}) from error

    def save(self, *args, **kwargs):
        from .criteria_policy import locked
        from .scoring import validate_weight

        try:
            validate_weight(self)
        except ValueError as error:
            raise ValidationError({"weight_percent": str(error)}) from error

        with transaction.atomic():
            old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
            ids = {self.partner_program_id}
            if old:
                ids.add(old.partner_program_id)
            programs = list(
                PartnerProgram.objects.select_for_update()
                .filter(pk__in=ids)
                .order_by("pk")
            )
            current = type(self).objects.filter(pk=self.pk).first() if self.pk else None
            if (old is not None and current is None) or (
                current is not None and current.partner_program_id not in ids
            ):
                raise ValidationError("Критерий изменился. Обновите данные.")
            old = current
            changed = old is None or any(
                getattr(old, field) != getattr(self, field)
                for field in (
                    "name",
                    "description",
                    "type",
                    "min_value",
                    "max_value",
                    "weight_percent",
                    "partner_program_id",
                )
            )
            if changed and any(locked(p) for p in programs):
                raise ValidationError("После первой оценки критерии нельзя менять.")
            if changed:
                from .scoring import validate_configuration

                for program in programs:
                    rows = list(program.criterias.exclude(pk=self.pk))
                    if program.pk == self.partner_program_id:
                        rows.append(self)
                    validate_configuration(program, rows)
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return type(self).objects.filter(pk=self.pk).delete()

    def __str__(self):
        return f"Criteria<{self.id}> - {self.name} {self.partner_program.name}"

    class Meta:
        verbose_name = "Критерий оценки проекта"
        verbose_name_plural = "Критерии оценки проектов"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(weight_percent__isnull=True)
                | (
                    models.Q(type__in=("int", "float"))
                    & models.Q(weight_percent__gt=0, weight_percent__lte=100)
                ),
                name="criterion_weight_numeric_positive",
            )
        ]


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
        verbose_name="Значение", max_length=1000, null=True, blank=True
    )

    def __str__(self):
        return f"ProjectScore<{self.id}> - {self.criteria.name}"

    def save(self, *args, **kwargs):
        from .criteria_policy import mark_locked

        program_id = Criteria.objects.values_list("partner_program_id", flat=True).get(
            pk=self.criteria_id
        )
        with transaction.atomic():
            program = PartnerProgram.objects.select_for_update().get(pk=program_id)
            from .scoring import validate_configuration

            validate_configuration(program)
            self.criteria = Criteria.objects.get(pk=self.criteria_id)
            if self.criteria.partner_program_id != program.pk:
                raise ValidationError("Критерий изменился. Обновите форму оценки.")
            ProjectScoreValidator.validate(
                criteria_type=self.criteria.type,
                value=self.value,
                criteria_min_value=self.criteria.min_value,
                criteria_max_value=self.criteria.max_value,
            )
            super().save(*args, **kwargs)
            mark_locked(program)

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
        from rest_framework.exceptions import APIException

        from project_rates.program_experts import program_experts

        errors = {}

        expert = None
        if self.expert_id and self.partner_program_id:
            expert = program_experts(self.partner_program_id).filter(pk=self.expert_id).first()
            if expert is None:
                errors["expert"] = "Эксперт не состоит в указанной программе."

        if (
            self.project_id
            and self.partner_program_id
            and not PartnerProgramProject.objects.filter(
                partner_program_id=self.partner_program_id,
                project_id=self.project_id,
            ).exists()
        ):
            errors["project"] = "Проект не привязан к указанной программе."

        if not errors and expert and expert.is_organizer and self.project_id:
            previous = type(self).objects.filter(pk=self.pk).values_list(
                "partner_program_id", "project_id", "expert_id"
            ).first()
            if previous != (self.partner_program_id, self.project_id, self.expert_id):
                from project_rates.workspace import validate_organizer_project_assignments

                try:
                    validate_organizer_project_assignments(
                        self.partner_program, expert, [self.project_id]
                    )
                except APIException as exc:
                    detail = exc.detail.get("detail") if isinstance(exc.detail, dict) else exc.detail[0]
                    errors["project"] = detail

        if self.partner_program_id and self.project_id:
            max_rates = self.partner_program.max_project_rates
            if max_rates and self.partner_program.required_evaluators is None:
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


class ExpertCaseScope(models.Model):
    """Program-specific eligibility; no row means all current and future cases."""

    partner_program = models.ForeignKey(
        PartnerProgram, on_delete=models.CASCADE, related_name="expert_case_scopes"
    )
    expert = models.ForeignKey(
        "users.Expert", on_delete=models.CASCADE, related_name="case_scopes"
    )
    all_cases = models.BooleanField(default=True)
    case_names = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["partner_program", "expert"],
                name="unique_program_expert_case_scope",
            )
        ]


class ExpertInvitation(models.Model):
    """Email invitation; only a digest of the bearer credential is stored."""

    partner_program = models.ForeignKey(
        PartnerProgram, on_delete=models.CASCADE, related_name="expert_invitations"
    )
    email = models.EmailField()
    all_cases = models.BooleanField(default=True)
    case_names = models.JSONField(default=list, blank=True)
    token_digest = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=12,
        default="pending",
        choices=[(v, v) for v in ("pending", "accepted", "revoked")],
    )
    delivery_status = models.CharField(
        max_length=12,
        default="queued",
        choices=[(v, v) for v in ("queued", "sent", "failed")],
    )
    invited_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="sent_expert_invitations"
    )
    accepted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="accepted_expert_invitations",
    )
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["partner_program", "email"],
                condition=models.Q(status="pending"),
                name="unique_pending_expert_program_email",
            )
        ]
        indexes = [models.Index(fields=["email", "status"])]


class ExpertJoinedNotification(models.Model):
    """One durable organizer receipt for an authenticated invitation acceptance."""

    invitation = models.ForeignKey(
        ExpertInvitation, on_delete=models.CASCADE, related_name="joined_notifications"
    )
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="expert_joined_notifications"
    )
    expert_name = models.CharField(max_length=800)
    expert_email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["invitation", "recipient"], name="unique_expert_joined_recipient"
            )
        ]


from .solution_models import SolutionScore, SolutionExpertAssignment  # noqa: E402,F401
