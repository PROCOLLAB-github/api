from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q, Value
from django.db.models.functions import Concat, Lower
from django.utils import timezone

from partner_programs.models import (
    Application,
    PartnerProgram,
    PartnerProgramUserProfile,
    Team,
    TeamInvite,
    TeamMember,
)
from partner_programs.permissions import can_manage_team
from partner_programs.services.application_team import (
    ActiveApplicationConflictError,
    ApplicationDeadlinePassedError,
    ApplicationNotEditableError,
    ApplicationTeamServiceError,
    require_no_active_conflict,
)

User = get_user_model()

TEAM_INVITE_CANDIDATE_LIMIT = 20


class TeamInvitePermissionError(ApplicationTeamServiceError):
    code = "team_invite_permission_denied"
    default_detail = "Недостаточно прав для управления приглашениями команды."
    default_field = "team"


class TeamInviteNotPendingError(ApplicationTeamServiceError):
    code = "team_invite_not_pending"
    default_detail = "Приглашение уже завершено и не может быть изменено."
    default_field = "status"


class TeamInviteTargetInvalidError(ApplicationTeamServiceError):
    code = "team_invite_target_invalid"
    default_detail = "Пользователя нельзя пригласить в эту команду."
    default_field = "user_id"


class TeamInviteRegistrationMissingError(ApplicationTeamServiceError):
    code = "team_invite_registration_missing"
    default_detail = "Пользователь не зарегистрирован на активность."
    default_field = "user_id"


class TeamInviteDuplicateError(ApplicationTeamServiceError):
    code = "team_invite_duplicate"
    default_detail = "Активное приглашение для этого пользователя уже существует."
    default_field = "user_id"


class TeamInviteCapacityReachedError(ApplicationTeamServiceError):
    code = "team_invite_capacity_reached"
    default_detail = "В команде нет свободного места для нового приглашения."
    default_field = "team"


class TeamInviteActiveApplicationConflictError(ApplicationTeamServiceError):
    code = "team_invite_active_application_conflict"
    default_detail = (
        "Пользователь уже участвует в другой активной заявке этой программы."
    )
    default_field = "user_id"


class TeamInviteNotOwnedError(ApplicationTeamServiceError):
    code = "team_invite_not_owned"
    default_detail = "Это приглашение предназначено другому пользователю."
    default_field = "invite"


@dataclass(frozen=True)
class TeamInviteCreationResult:
    """Результат идемпотентного создания приглашения."""

    invite: TeamInvite
    created: bool


def _lock_team_graph(team: Team) -> tuple[PartnerProgram, Application, Team]:
    """Блокирует Program → Application → Team в общем порядке domain-операций."""
    program_id = team.application.program_id
    application_id = team.application_id

    program = PartnerProgram.objects.select_for_update().get(pk=program_id)
    application = (
        Application.objects.select_for_update()
        .select_related("program", "user", "created_by", "project")
        .get(pk=application_id)
    )
    locked_team = (
        Team.objects.select_for_update()
        .select_related("application", "application__program", "captain")
        .get(pk=team.pk)
    )
    return program, application, locked_team


def _lock_invite_graph(
    invite: TeamInvite,
) -> tuple[PartnerProgram, Application, Team, TeamInvite]:
    """Блокирует граф приглашения в том же порядке, что и операции Team."""
    program, application, team = _lock_team_graph(invite.team)
    locked_invite = (
        TeamInvite.objects.select_for_update()
        .select_related("team", "team__application", "user", "invited_by")
        .get(pk=invite.pk)
    )
    return program, application, team, locked_invite


def _require_mutable_invites(
    *,
    application: Application,
    program: PartnerProgram,
) -> None:
    """Разрешает приглашения только для draft-заявки до ее дедлайна."""
    if application.status != Application.STATUS_DRAFT:
        raise ApplicationNotEditableError(
            "Приглашения можно изменять только в черновике заявки."
        )
    if program.is_application_deadline_passed():
        raise ApplicationDeadlinePassedError()


def _require_registered_target(*, program: PartnerProgram, user: User) -> None:
    if not PartnerProgramUserProfile.objects.filter(
        partner_program=program,
        user=user,
    ).exists():
        raise TeamInviteRegistrationMissingError()


def _require_no_target_conflict(*, program: PartnerProgram, user: User) -> None:
    try:
        require_no_active_conflict(program=program, user=user)
    except ActiveApplicationConflictError as exc:
        raise TeamInviteActiveApplicationConflictError() from exc


def _accepted_members_count(team: Team) -> int:
    return TeamMember.objects.select_for_update().filter(
        team=team,
        status=TeamMember.STATUS_ACCEPTED,
    ).count()


def _pending_invites_count(team: Team) -> int:
    return TeamInvite.objects.select_for_update().filter(
        team=team,
        status=TeamInvite.STATUS_PENDING,
    ).count()


def _require_invite_capacity(*, team: Team, program: PartnerProgram) -> None:
    maximum = program.team_max_size
    if maximum is None or (
        _accepted_members_count(team) + _pending_invites_count(team) >= maximum
    ):
        raise TeamInviteCapacityReachedError()


def _require_accept_capacity(*, team: Team, program: PartnerProgram) -> None:
    maximum = program.team_max_size
    if maximum is None or _accepted_members_count(team) >= maximum:
        raise TeamInviteCapacityReachedError()


def get_team_invite_candidates(
    *,
    team: Team,
    actor: User,
    query: str,
):
    """Возвращает ограниченный queryset потенциальных участников Team.

    Eligibility выражена через Exists-подзапросы: связанные Application,
    TeamMember и TeamInvite не размножают строки пользователя и не требуют
    широкого `distinct()`. Selector не резервирует место; create service
    повторяет проверки под блокировкой Program.
    """
    if not can_manage_team(actor, team):
        raise TeamInvitePermissionError()

    application = team.application
    program = application.program
    if application.participation_mode != Application.PARTICIPATION_MODE_TEAM:
        raise TeamInviteTargetInvalidError(
            "Поиск кандидатов доступен только для командной заявки.",
            field="team",
        )
    _require_mutable_invites(application=application, program=program)

    accepted_count = TeamMember.objects.filter(
        team=team,
        status=TeamMember.STATUS_ACCEPTED,
    ).count()
    pending_count = TeamInvite.objects.filter(
        team=team,
        status=TeamInvite.STATUS_PENDING,
    ).count()
    if (
        program.team_max_size is None
        or accepted_count + pending_count >= program.team_max_size
    ):
        raise TeamInviteCapacityReachedError()

    registrations = PartnerProgramUserProfile.objects.filter(
        partner_program=program,
        user_id=OuterRef("pk"),
    )
    pending_current_invites = TeamInvite.objects.filter(
        team=team,
        user_id=OuterRef("pk"),
        status=TeamInvite.STATUS_PENDING,
    )
    active_owned_applications = Application.objects.filter(
        program=program,
        user_id=OuterRef("pk"),
        status__in=Application.ACTIVE_STATUSES,
    )
    active_team_memberships = TeamMember.objects.filter(
        user_id=OuterRef("pk"),
        status=TeamMember.STATUS_ACCEPTED,
        team__application__program=program,
        team__application__status__in=Application.ACTIVE_STATUSES,
    )

    normalized_query = query.strip()
    # SQLite не нормализует регистр кириллицы для ILIKE так же, как production
    # PostgreSQL. Небольшой набор Unicode-вариантов сохраняет ORM-фильтрацию и
    # одинаковый контракт для обычного lower/UPPER/Title ввода.
    query_variants = dict.fromkeys(
        (
            normalized_query,
            normalized_query.casefold(),
            normalized_query.lower(),
            normalized_query.upper(),
            normalized_query.title(),
            normalized_query.capitalize(),
        )
    )
    search_filter = Q()
    for query_variant in query_variants:
        search_filter |= (
            Q(first_name__icontains=query_variant)
            | Q(last_name__icontains=query_variant)
            | Q(candidate_full_name__icontains=query_variant)
            | Q(candidate_reverse_name__icontains=query_variant)
            | Q(email__istartswith=query_variant)
        )

    # Минимальная длина query и жесткий limit не позволяют использовать этот
    # scoped endpoint как глобальное перечисление пользователей платформы.
    return (
        User.objects.annotate(
            candidate_full_name=Concat(
                "first_name",
                Value(" "),
                "last_name",
            ),
            candidate_reverse_name=Concat(
                "last_name",
                Value(" "),
                "first_name",
            ),
            candidate_is_registered=Exists(registrations),
            candidate_has_pending_invite=Exists(pending_current_invites),
            candidate_has_active_application=Exists(active_owned_applications),
            candidate_has_active_membership=Exists(active_team_memberships),
        )
        .filter(
            is_active=True,
            candidate_is_registered=True,
            candidate_has_pending_invite=False,
            candidate_has_active_application=False,
            candidate_has_active_membership=False,
        )
        .exclude(pk=team.captain_id)
        .filter(search_filter)
        .only("id", "first_name", "last_name", "avatar")
        .order_by(Lower("last_name"), Lower("first_name"), "pk")[
            :TEAM_INVITE_CANDIDATE_LIMIT
        ]
    )


def create_team_invite(
    *,
    team: Team,
    actor: User,
    target: User,
) -> TeamInviteCreationResult:
    """Создает pending-приглашение без создания предварительного TeamMember.

    Повторный запрос для того же pending-приглашения возвращает существующую
    запись. Program блокируется первым, чтобы проверки конфликтов и вместимости
    оставались согласованными с параллельными операциями над другими командами.
    """
    with transaction.atomic():
        program, application, team = _lock_team_graph(team)
        if not can_manage_team(actor, team):
            raise TeamInvitePermissionError()
        _require_mutable_invites(application=application, program=program)

        if (
            application.participation_mode != Application.PARTICIPATION_MODE_TEAM
            or target.pk == team.captain_id
            or TeamMember.objects.select_for_update().filter(
                team=team,
                user=target,
                status=TeamMember.STATUS_ACCEPTED,
            ).exists()
        ):
            raise TeamInviteTargetInvalidError()

        existing = TeamInvite.objects.select_for_update().filter(
            team=team,
            user=target,
            status=TeamInvite.STATUS_PENDING,
        ).first()
        if existing is not None:
            return TeamInviteCreationResult(existing, created=False)

        _require_registered_target(program=program, user=target)
        _require_no_target_conflict(program=program, user=target)
        _require_invite_capacity(team=team, program=program)

        try:
            # Вложенная транзакция сохраняет внешнюю при IntegrityError в гонке.
            with transaction.atomic():
                invite = TeamInvite.objects.create(
                    team=team,
                    user=target,
                    invited_by=actor,
                )
        except IntegrityError as exc:
            invite = TeamInvite.objects.filter(
                team=team,
                user=target,
                status=TeamInvite.STATUS_PENDING,
            ).first()
            if invite is None:
                raise TeamInviteDuplicateError() from exc
            return TeamInviteCreationResult(invite, created=False)

        return TeamInviteCreationResult(invite, created=True)


def accept_team_invite(*, invite: TeamInvite, actor: User) -> TeamInvite:
    """Атомарно принимает приглашение и создает либо восстанавливает membership.

    Принятое приглашение идемпотентно. Только первый переход из pending повторно
    проверяет Registration, конфликт участия, вместимость и открытый draft.
    """
    with transaction.atomic():
        program, application, team, invite = _lock_invite_graph(invite)
        if invite.user_id != actor.pk:
            raise TeamInviteNotOwnedError()
        if invite.status == TeamInvite.STATUS_ACCEPTED:
            return invite
        if invite.status != TeamInvite.STATUS_PENDING:
            raise TeamInviteNotPendingError()

        _require_mutable_invites(application=application, program=program)
        _require_registered_target(program=program, user=invite.user)
        _require_no_target_conflict(program=program, user=invite.user)

        member = TeamMember.objects.select_for_update().filter(
            team=team,
            user=invite.user,
        ).first()
        if member is not None and member.status == TeamMember.STATUS_ACCEPTED:
            raise TeamInviteTargetInvalidError(
                "Пользователь уже является участником этой команды."
            )
        _require_accept_capacity(team=team, program=program)

        if member is None:
            member = TeamMember(
                team=team,
                user=invite.user,
                role=TeamMember.ROLE_MEMBER,
                status=TeamMember.STATUS_ACCEPTED,
                invited_by=invite.invited_by,
            )
        else:
            member.role = TeamMember.ROLE_MEMBER
            member.status = TeamMember.STATUS_ACCEPTED
            member.invited_by = invite.invited_by
        member.save()

        resolved_at = timezone.now()
        invite.status = TeamInvite.STATUS_ACCEPTED
        invite.resolved_at = resolved_at
        invite.save(update_fields=["status", "resolved_at", "updated_at"])

        # Принятие места в одной команде закрывает конкурирующие pending-инвайты
        # этого пользователя в рамках той же Program, но сохраняет их историю.
        other_invites = TeamInvite.objects.select_for_update().filter(
            user=invite.user,
            status=TeamInvite.STATUS_PENDING,
            team__application__program=program,
        ).exclude(pk=invite.pk)
        list(other_invites.values_list("pk", flat=True))
        other_invites.update(
            status=TeamInvite.STATUS_REVOKED,
            resolved_at=resolved_at,
            updated_at=resolved_at,
        )
        return invite


def decline_team_invite(*, invite: TeamInvite, actor: User) -> TeamInvite:
    """Отклоняет принадлежащее пользователю pending-приглашение."""
    with transaction.atomic():
        program, application, _team, invite = _lock_invite_graph(invite)
        if invite.user_id != actor.pk:
            raise TeamInviteNotOwnedError()
        if invite.status == TeamInvite.STATUS_DECLINED:
            return invite
        if invite.status != TeamInvite.STATUS_PENDING:
            raise TeamInviteNotPendingError()

        _require_mutable_invites(application=application, program=program)
        invite.status = TeamInvite.STATUS_DECLINED
        invite.resolved_at = timezone.now()
        invite.save(update_fields=["status", "resolved_at", "updated_at"])
        return invite


def revoke_team_invite(*, invite: TeamInvite, actor: User) -> TeamInvite:
    """Отзывает pending-приглашение капитаном команды или staff."""
    with transaction.atomic():
        program, application, team, invite = _lock_invite_graph(invite)
        if not can_manage_team(actor, team):
            raise TeamInvitePermissionError()
        if invite.status == TeamInvite.STATUS_REVOKED:
            return invite
        if invite.status != TeamInvite.STATUS_PENDING:
            raise TeamInviteNotPendingError()

        _require_mutable_invites(application=application, program=program)
        invite.status = TeamInvite.STATUS_REVOKED
        invite.resolved_at = timezone.now()
        invite.save(update_fields=["status", "resolved_at", "updated_at"])
        return invite
