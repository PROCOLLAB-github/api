"""Приглашения решения используют общий с командой порядок блокировок."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404

from partner_programs import solution_team
from partner_programs.solution_errors import MAX_ID, SolutionError
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionMember,
    SolutionInvitation,
)


def visible_invitations(actor):
    return SolutionInvitation.objects.filter(
        Q(recipient=actor) | Q(solution__captain=actor)
    ).select_related("recipient", "solution__program", "solution__captain")


def require_enabled(solution):
    if solution.program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует заявки на основе проектов."
        )


def require_pending(invitation):
    if invitation.status != "pending":
        raise SolutionError("invite_already_processed", "Приглашение уже обработано.")


def require_version(invitation, expected):
    if str(invitation.version) != str(expected):
        raise SolutionError(
            "version_conflict",
            "Приглашение изменилось. Обновите данные и повторите действие.",
            meta={"current_version": invitation.version},
        )


def require_recipient(invitation, actor):
    if invitation.recipient_id != actor.pk:
        raise SolutionError(
            "not_invite_recipient",
            "Ответить на приглашение может только получатель.",
            status=403,
        )


def require_eligible(solution, user_id):
    if user_id in solution_team.accepted_user_ids(solution):
        raise SolutionError(
            "already_solution_member", "Пользователь уже состоит в команде."
        )


def require_fields(fields):
    if fields.keys() - {"role", "specialization", "motivational_letter"}:
        raise SolutionError(
            "validation_error", "Недопустимые поля приглашения.", status=400
        )


def lock_invitation(invitation_id, actor):
    if not 0 < invitation_id <= MAX_ID:
        raise Http404
    try:
        reference = visible_invitations(actor).get(pk=invitation_id)
    except SolutionInvitation.DoesNotExist:
        raise Http404
    program = solution_team.program_for(reference.solution.program_id, lock=True)
    solution = ProgramSolution.objects.select_for_update().get(
        pk=reference.solution_id, program=program
    )
    try:
        invitation = SolutionInvitation.objects.select_for_update().get(
            pk=invitation_id, solution=solution
        )
    except SolutionInvitation.DoesNotExist:
        raise Http404
    solution.program = program
    invitation.solution = solution
    # Капитан мог смениться, пока ожидалась общая блокировка программы.
    if actor.pk not in (solution.captain_id, invitation.recipient_id):
        raise Http404
    return solution, invitation


def advance_invitation(invitation, *, fields):
    invitation.version += 1
    invitation.save(update_fields=[*fields, "version", "updated_at"])
    solution_team.advance_version(invitation.solution)
    return invitation


@transaction.atomic
def create_invitation(
    *,
    program_id,
    solution_id,
    actor,
    expected_solution_version,
    recipient_user_id,
    **fields
):
    require_fields(fields)
    solution = solution_team.lock_solution(program_id, solution_id, actor)
    solution_team.require_captain(solution, actor)
    solution_team.require_mutable(solution)
    solution_team.require_version(solution, expected_solution_version)
    if (
        not 0 < recipient_user_id <= MAX_ID
        or not get_user_model().objects.filter(pk=recipient_user_id).exists()
    ):
        raise Http404
    require_eligible(solution, recipient_user_id)
    pending = solution.invitations.filter(
        recipient_id=recipient_user_id, status="pending"
    )
    if pending.exists():
        raise SolutionError(
            "duplicate_pending_invite", "Приглашение этому участнику уже отправлено."
        )
    solution_team.validate_new_member(solution, recipient_user_id)
    try:
        with transaction.atomic():
            invitation = SolutionInvitation.objects.create(
                solution=solution, recipient_id=recipient_user_id, **fields
            )
    except IntegrityError as error:
        if pending.exists():
            raise SolutionError(
                "duplicate_pending_invite", "Приглашение этому участнику уже отправлено."
            ) from error
        raise
    solution_team.advance_version(solution)
    return invitation


@transaction.atomic
def update_invitation(
    *, invitation_id, actor, expected_version, expected_solution_version, **fields
):
    require_fields(fields)
    solution, invitation = lock_invitation(invitation_id, actor)
    solution_team.require_captain(solution, actor)
    solution_team.require_mutable(solution)
    require_pending(invitation)
    require_version(invitation, expected_version)
    solution_team.require_version(solution, expected_solution_version)
    require_eligible(solution, invitation.recipient_id)
    solution_team.validate_new_member(solution, invitation.recipient_id)
    for field, value in fields.items():
        setattr(invitation, field, value)
    return advance_invitation(invitation, fields=fields)


@transaction.atomic
def revoke_invitation(
    *, invitation_id, actor, expected_version, expected_solution_version
):
    solution, invitation = lock_invitation(invitation_id, actor)
    solution_team.require_captain(solution, actor)
    require_enabled(solution)
    require_pending(invitation)
    require_version(invitation, expected_version)
    solution_team.require_version(solution, expected_solution_version)
    invitation.delete()
    solution_team.advance_version(solution)


@transaction.atomic
def decide_invitation(*, invitation_id, actor, expected_version, accept):
    solution, invitation = lock_invitation(invitation_id, actor)
    require_recipient(invitation, actor)
    require_enabled(solution)
    require_pending(invitation)
    require_version(invitation, expected_version)
    if accept:
        require_eligible(solution, actor.pk)
        solution_team.validate_new_member(solution, actor.pk)
        ProgramSolutionMember.objects.create(
            solution=solution,
            user=actor,
            role=invitation.role,
            specialization=invitation.specialization,
        )
    invitation.status = "accepted" if accept else "declined"
    return advance_invitation(invitation, fields=["status"])
