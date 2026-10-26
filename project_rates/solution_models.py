"""Оценки и реальные назначения новой сущности; общие Criteria/Expert сохраняются."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from partner_programs.models import PartnerProgram
from partner_programs.solution_models import ProgramSolution
from project_rates.validators import ProjectScoreValidator


class SolutionScore(models.Model):
    criteria = models.ForeignKey(
        "project_rates.Criteria", on_delete=models.CASCADE, related_name="solution_scores"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="solution_scores"
    )
    solution = models.ForeignKey(
        "partner_programs.ProgramSolution",
        on_delete=models.CASCADE,
        related_name="scores",
    )
    value = models.CharField(max_length=1000, null=True, blank=True)

    class Meta:
        verbose_name = "Оценка решения"
        verbose_name_plural = "Оценки решений"
        constraints = [
            models.UniqueConstraint(
                fields=["criteria", "user", "solution"],
                name="unique_solution_score_criterion_user",
            )
        ]
        indexes = [
            models.Index(fields=["solution", "user"], name="solution_score_rater_idx")
        ]

    def clean(self):
        super().clean()
        from project_rates.models import Criteria

        criterion = Criteria.objects.filter(pk=self.criteria_id).first()
        solution = ProgramSolution.all_objects.filter(pk=self.solution_id).first()
        if solution and solution.archived_at is not None:
            raise ValidationError({"solution": "Решение снято с участия."})
        if criterion and solution and criterion.partner_program_id != solution.program_id:
            raise ValidationError({"criteria": "Критерий относится к другой программе."})
        if solution and solution.status != "submitted":
            raise ValidationError({"solution": "Сначала нужно сдать решение."})
        if criterion:
            try:
                ProjectScoreValidator.validate(
                    criteria_type=criterion.type,
                    value=self.value,
                    criteria_min_value=criterion.min_value,
                    criteria_max_value=criterion.max_value,
                )
            except (TypeError, ValueError) as error:
                raise ValidationError({"value": str(error)}) from error

    @transaction.atomic
    def save(self, *args, **kwargs):
        from project_rates.models import Criteria
        from project_rates.criteria_policy import mark_locked

        criterion = Criteria.objects.get(pk=self.criteria_id)
        program = PartnerProgram.objects.select_for_update().get(
            pk=criterion.partner_program_id
        )
        if Criteria.objects.get(pk=self.criteria_id).partner_program_id != program.pk:
            raise ValidationError(
                {"criteria": "Критерии изменились. Обновите форму оценки."},
                code="criteria_changed",
            )
        self.full_clean()
        result = super().save(*args, **kwargs)
        mark_locked(program)
        return result


class SolutionAssignmentQuerySet(models.QuerySet):
    @transaction.atomic
    def delete(self):
        program_ids = self.values_list("partner_program_id", flat=True).distinct()
        list(
            PartnerProgram.objects.select_for_update()
            .filter(pk__in=program_ids)
            .order_by("pk")
        )
        rows = list(self.select_related("expert").order_by("pk"))
        if any(row.has_scores() for row in rows):
            raise ValidationError(
                "Нельзя снять назначение с сохраненными оценками.",
                code="scores_protected",
            )
        return super().delete()


class SolutionExpertAssignment(models.Model):
    partner_program = models.ForeignKey(
        "partner_programs.PartnerProgram",
        on_delete=models.CASCADE,
        related_name="solution_expert_assignments",
    )
    solution = models.ForeignKey(
        "partner_programs.ProgramSolution",
        on_delete=models.CASCADE,
        related_name="expert_assignments",
    )
    expert = models.ForeignKey(
        "users.Expert", on_delete=models.CASCADE, related_name="solution_assignments"
    )
    datetime_created = models.DateTimeField(auto_now_add=True)
    datetime_updated = models.DateTimeField(auto_now=True)
    objects = SolutionAssignmentQuerySet.as_manager()

    class Meta:
        verbose_name = "Назначение эксперта на решение"
        verbose_name_plural = "Назначения экспертов на решения"
        constraints = [
            models.UniqueConstraint(
                fields=["partner_program", "solution", "expert"],
                name="unique_solution_expert_assignment",
            )
        ]
        indexes = [
            models.Index(
                fields=["partner_program", "solution"],
                name="solution_assignment_scope_idx",
            ),
            models.Index(
                fields=["partner_program", "expert"],
                name="solution_assignment_expert_idx",
            ),
        ]

    def has_scores(self):
        return SolutionScore.objects.filter(
            solution_id=self.solution_id,
            user_id=self.expert.user_id,
            criteria__partner_program_id=self.partner_program_id,
        ).exists()

    def clean(self):
        super().clean()
        from users.models import Expert
        from project_rates.models import ExpertCaseScope
        from project_rates.workspace import eligible, target

        if not self.partner_program_id or not self.solution_id or not self.expert_id:
            return

        solution = ProgramSolution.all_objects.filter(pk=self.solution_id).first()
        if solution and solution.archived_at is not None:
            raise ValidationError({"solution": "Решение снято с участия."})
        expert = Expert.objects.filter(
            pk=self.expert_id, programs__pk=self.partner_program_id, user__is_active=True
        ).first()
        if expert is None:
            raise ValidationError(
                {"expert": "Выберите активного эксперта этой программы."}
            )
        if not solution or solution.program_id != self.partner_program_id:
            raise ValidationError({"solution": "Решение относится к другой программе."})
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        changed = previous is None or (
            previous.partner_program_id,
            previous.solution_id,
            previous.expert_id,
        ) != (self.partner_program_id, self.solution_id, self.expert_id)
        if previous and changed:
            raise ValidationError("Назначение нельзя переназначить; создайте новое.")
        if not changed:
            return
        if solution.status != "submitted":
            raise ValidationError({"solution": "Назначать можно только сданное решение."})
        snapshot = solution.submission_snapshot or {}
        team_ids = {row["user"]["id"] for row in snapshot.get("members", [])}
        team_ids.add(snapshot.get("captain_id", solution.captain_id))
        if expert.user_id in team_ids:
            raise ValidationError(
                {"expert": "Нельзя назначить эксперта на свою команду."}
            )
        case_field = next(
            (
                field
                for field in snapshot.get("form", {}).get("fields", [])
                if field["purpose"] == "case"
            ),
            None,
        )
        case_name = next(
            (
                answer["value"]
                for answer in snapshot.get("answers", [])
                if case_field and answer["field_id"] == case_field["id"]
            ),
            None,
        )
        scope = ExpertCaseScope.objects.filter(
            partner_program_id=self.partner_program_id, expert=expert
        ).first()
        if not eligible(scope, case_name):
            raise ValidationError({"expert": "Кейс недоступен этому эксперту."})
        count = (
            type(self)
            .objects.filter(partner_program_id=self.partner_program_id, solution=solution)
            .count()
        )
        if count >= target(solution.program):
            raise ValidationError("Достигнут лимит новых назначений экспертов.")

    @transaction.atomic
    def save(self, *args, **kwargs):
        PartnerProgram.objects.select_for_update().get(pk=self.partner_program_id)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return type(self).objects.filter(pk=self.pk).delete()
