from django.db import transaction

from project_rates.solution_evaluation import snapshot_name
from vacancy.mapping import MessageTypeEnum, SolutionRatedParams
from vacancy.tasks import send_email


def notify_solution_rated(solution):
    payload = SolutionRatedParams(
        message_type=MessageTypeEnum.SOLUTION_RATED.value,
        user_id=solution.captain_id,
        schema_id=2,
        program_name=solution.program.name,
        program_id=solution.program_id,
        solution_name=snapshot_name(solution),
        solution_id=solution.pk,
    )
    transaction.on_commit(lambda: send_email.delay(payload), robust=True)
