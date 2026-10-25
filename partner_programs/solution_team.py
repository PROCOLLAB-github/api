"""Владелец состава — решение; общие ограничения сохраняются с legacy-командой."""

from django.db import transaction
from django.db.models import Q
from django.http import Http404

from partner_programs.models import PartnerProgram
from partner_programs.permissions import can_manage_program
from partner_programs.solution_errors import MAX_ID, SolutionError
from partner_programs.solution_models import ProgramSolution
from projects import team_policy
from projects.team_errors import TeamError


def program_for(pk, *, lock=False):
    if not 0 < pk <= MAX_ID:
        raise Http404
    query = PartnerProgram.objects.select_for_update() if lock else PartnerProgram.objects
    try:
        return query.get(pk=pk)
    except PartnerProgram.DoesNotExist:
        raise Http404


def visible_solutions(program, user, *, include_archived=False):
    manager = ProgramSolution.all_objects if include_archived else ProgramSolution.objects
    query = manager.filter(program=program)
    # Эксперт получает сданные работы своей программы в пределах режима назначений.
    if can_manage_program(user, program):
        return query
    from project_rates.solution_evaluation import expert_visible_solutions

    return query.filter(
        Q(captain=user)
        | Q(members__user=user)
        | Q(pk__in=expert_visible_solutions(program, user).order_by().values("pk"))
    ).distinct()


def lock_solution(program_id, solution_id, actor):
    program = program_for(program_id, lock=True)
    if not 0 < solution_id <= MAX_ID:
        raise Http404
    # Отдельный EXISTS до FOR UPDATE: DISTINCT нельзя блокировать в PostgreSQL.
    if (
        not visible_solutions(program, actor, include_archived=True)
        .filter(pk=solution_id)
        .exists()
    ):
        raise Http404
    solution = ProgramSolution.all_objects.select_for_update().get(
        pk=solution_id, program=program
    )
    solution.program = program
    return solution


def require_mutable(solution):
    if solution.program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует заявки на основе проектов."
        )
    require_active(solution)
    if solution.status == "submitted":
        raise SolutionError("team_frozen", "Состав команды зафиксирован после сдачи.")


def require_active(solution):
    if solution.archived_at is not None:
        raise SolutionError(
            "solution_archived",
            "Решение снято с участия. Материалы доступны для просмотра.",
        )


def require_captain(solution, actor):
    if solution.captain_id != actor.pk:
        raise SolutionError(
            "not_solution_captain", "Управлять командой может только капитан.", status=403
        )


def require_version(solution, expected):
    if str(solution.version) != str(expected):
        raise SolutionError(
            "version_conflict",
            "Заявка изменилась. Обновите данные и повторите действие.",
            meta={"current_version": solution.version},
        )


def accepted_user_ids(solution):
    return {solution.captain_id} | set(solution.members.values_list("user_id", flat=True))


def reserved_user_ids(solution):
    return accepted_user_ids(solution) | set(
        solution.invitations.filter(status="pending").values_list(
            "recipient_id", flat=True
        )
    )


def validate_users(solution, user_ids):
    try:
        team_policy.validate_program_users(
            solution.program,
            project_id=None,
            solution_id=solution.pk,
            user_ids=user_ids,
            lock=True,
        )
    except TeamError as error:
        raise SolutionError(
            str(error.detail["code"]), str(error.detail["detail"]), error.status_code
        ) from error


def validate_max_size(solution, user_ids):
    try:
        team_policy.validate_max_size(solution.program, user_ids)
    except TeamError as error:
        raise SolutionError(
            str(error.detail["code"]), str(error.detail["detail"]), error.status_code
        ) from error


def validate_new_member(solution, user_id):
    """BE03 использует под теми же блокировками; свой pending резерв не удваивается."""
    require_mutable(solution)
    validate_users(solution, {user_id})
    validate_max_size(solution, reserved_user_ids(solution) | {user_id})


def validate_submission_team(solution):
    members = accepted_user_ids(solution)
    validate_users(solution, members)
    if solution.program.is_competitive:
        minimum = solution.program.legacy_team_min_size
        if minimum is not None and len(members) < minimum:
            raise SolutionError(
                "team_min_size", f"Для сдачи нужно не менее {minimum} участников."
            )
        validate_max_size(solution, members)
    return members


def advance_version(solution, *, fields=()):
    solution.version += 1
    solution.save(update_fields=[*fields, "version", "updated_at"])
    return solution


def require_not_captain(solution, user_id):
    if solution.captain_id == user_id:
        raise SolutionError(
            "captain_cannot_leave", "Сначала передайте капитанство другому участнику."
        )


@transaction.atomic
def remove_member(*, program_id, solution_id, user_id, actor, expected_version):
    solution = lock_solution(program_id, solution_id, actor)
    require_captain(solution, actor)
    require_mutable(solution)
    require_version(solution, expected_version)
    require_not_captain(solution, user_id)
    if not 0 < user_id <= MAX_ID or not solution.members.filter(user_id=user_id).exists():
        raise Http404
    solution.members.filter(user_id=user_id).delete()
    return advance_version(solution)


@transaction.atomic
def leave_team(*, program_id, solution_id, actor, expected_version):
    solution = lock_solution(program_id, solution_id, actor)
    require_mutable(solution)
    require_version(solution, expected_version)
    require_not_captain(solution, actor.pk)
    if not solution.members.filter(user_id=actor.pk).exists():
        raise SolutionError(
            "not_solution_member", "Вы не состоите в этой команде.", status=403
        )
    solution.members.filter(user_id=actor.pk).delete()
    advance_version(solution)


@transaction.atomic
def transfer_captain(*, program_id, solution_id, user_id, actor, expected_version):
    solution = lock_solution(program_id, solution_id, actor)
    require_captain(solution, actor)
    require_mutable(solution)
    require_version(solution, expected_version)
    if user_id == solution.captain_id:
        raise SolutionError(
            "already_solution_captain", "Участник уже является капитаном."
        )
    if not 0 < user_id <= MAX_ID or not solution.members.filter(user_id=user_id).exists():
        raise SolutionError(
            "member_not_found", "Новый капитан должен быть участником команды."
        )
    validate_new_member(solution, user_id)
    if (
        ProgramSolution.objects.filter(program=solution.program, captain_id=user_id)
        .exclude(pk=solution.pk)
        .exists()
    ):
        raise SolutionError(
            "already_solution_captain",
            "Участник уже является капитаном другой заявки этой программы.",
        )
    solution.captain_id = user_id
    return advance_version(solution, fields=["captain"])
