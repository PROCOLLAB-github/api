from django.db.models.deletion import ProtectedError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionAnswer,
    ProgramSolutionMember,
    SolutionInvitation,
    lock_saved_solution,
)


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
    if (
        solution
        and solution.status == "submitted"
        and not (sender is SolutionInvitation and instance.status == "pending")
    ):
        raise ProtectedError(
            "Данные и состав сданного решения зафиксированы.", [instance]
        )
