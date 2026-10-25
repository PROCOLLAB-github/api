"""Case aggregates of owned solutions; legacy project links are never a source."""

from partner_programs.models import PartnerProgramUserProfile
from partner_programs.services.case_fields import get_program_case_field
from partner_programs.solution_models import ProgramSolution
from project_rates.solution_evaluation import snapshot_case, team_user_ids


def build_solution_case_analytics(program):
    field = get_program_case_field(program)
    options = field.get_options_list() if field else []

    def empty():
        return dict(
            participants_total=0,
            solutions_total=0,
            not_submitted=0 if program.is_competitive else None,
            submitted=0 if program.is_competitive else None,
        )

    buckets = {name: empty() for name in options}
    without_case = empty()
    participants = {name: set() for name in [*options, None]}
    registered = set(
        PartnerProgramUserProfile.objects.filter(
            partner_program=program, user_id__isnull=False
        ).values_list("user_id", flat=True)
    )
    rows = ProgramSolution.objects.filter(program=program).prefetch_related(
        "answers", "members"
    )
    for solution in rows:
        case = snapshot_case(solution, draft_field_id=field.pk if field else None)
        key = case if case in buckets else None
        metrics = buckets[key] if key is not None else without_case
        metrics["solutions_total"] += 1
        if program.is_competitive:
            state = "submitted" if solution.status == "submitted" else "not_submitted"
            metrics[state] += 1
        participants[key].update(team_user_ids(solution) & registered)
    for key, metrics in [*buckets.items(), (None, without_case)]:
        metrics["participants_total"] = len(participants[key])
    return dict(
        program_id=program.pk,
        configured=field is not None,
        submission_applicable=program.is_competitive,
        items=[dict(name=name, **metrics) for name, metrics in buckets.items()],
        without_case=without_case,
    )
