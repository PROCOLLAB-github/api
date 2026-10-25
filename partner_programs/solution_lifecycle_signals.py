from django.db.models.deletion import ProtectedError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionAnswer,
    ProgramSolutionMember,
    SolutionInvitation,
    SolutionAdministrativeChange,
    lock_saved_solution,
)


@receiver(
    pre_delete,
    sender=SolutionAdministrativeChange,
    dispatch_uid="protect_solution_administrative_history",
)
def protect_administrative_history(sender, instance, **kwargs):
    raise ProtectedError("Историю изменений нельзя удалять.", [instance])


@receiver(pre_delete, sender=ProgramSolution, dispatch_uid="protect_submitted_solution")
@receiver(
    pre_delete, sender=ProgramSolutionAnswer, dispatch_uid="protect_submitted_answer"
)
@receiver(
    pre_delete, sender=ProgramSolutionMember, dispatch_uid="protect_submitted_member"
)
@receiver(
    pre_delete, sender=SolutionInvitation, dispatch_uid="protect_submitted_invitation"
)
def protect_submitted_record(sender, instance, **kwargs):
    solution = lock_saved_solution(
        instance.pk if sender is ProgramSolution else instance.solution_id
    )
    if sender is ProgramSolutionMember:
        from partner_programs.services.solution_member_actions import (
            permits_member_deletion,
        )

        if permits_member_deletion(instance):
            return
    if (
        solution
        and solution.status == "submitted"
        and not (sender is SolutionInvitation and instance.status == "pending")
    ):
        raise ProtectedError(
            "Данные и состав сданного решения зафиксированы.", [instance]
        )
