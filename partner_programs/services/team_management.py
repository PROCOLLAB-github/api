from django.contrib.auth import get_user_model
from django.db import models, transaction

from partner_programs.models import (
    Application,
    PartnerProgram,
    PartnerProgramUserProfile,
    Team,
    TeamMember,
)
from partner_programs.permissions import can_manage_team, is_team_captain
from partner_programs.services.application_team import (
    ApplicationDeadlinePassedError,
    ApplicationNotEditableError,
    ApplicationTeamServiceError,
    CaptainMemberMissingError,
    CaptainMismatchError,
    TeamMemberRegistrationMissingError,
    require_no_active_conflict,
)

User = get_user_model()


class TeamManagementPermissionError(ApplicationTeamServiceError):
    code = "team_permission_denied"
    default_detail = "Недостаточно прав для управления командой."
    default_field = "team"


class CaptainTransferRequiredError(ApplicationTeamServiceError):
    code = "captain_transfer_required"
    default_detail = "Капитан должен сначала передать капитанство."
    default_field = "team"


class TeamMembershipNotActiveError(ApplicationTeamServiceError):
    code = "team_membership_not_active"
    default_detail = "Активное членство в команде не найдено."
    default_field = "team"


class TeamMemberNotFoundError(ApplicationTeamServiceError):
    code = "team_member_not_found"
    default_detail = "Участник этой команды не найден."
    default_field = "member_id"


class TeamMemberNotRemovableError(ApplicationTeamServiceError):
    code = "team_member_not_removable"
    default_detail = "Участника нельзя удалить в текущем состоянии."
    default_field = "member_id"


class CaptainTransferTargetInvalidError(ApplicationTeamServiceError):
    code = "captain_transfer_target_invalid"
    default_detail = "Капитанство можно передать принятому участнику команды."
    default_field = "member_id"


def _lock_team_graph(team: Team) -> tuple[PartnerProgram, Application, Team]:
    """Блокирует Program → Application → Team в едином порядке операций."""
    program_id = team.application.program_id
    application_id = team.application_id
    team_id = team.pk

    program = PartnerProgram.objects.select_for_update().get(pk=program_id)
    application = (
        Application.objects.select_for_update()
        .select_related("program", "user", "created_by", "project")
        .get(pk=application_id)
    )
    locked_team = (
        Team.objects.select_for_update()
        .select_related("application", "application__program", "captain")
        .get(pk=team_id)
    )
    return program, application, locked_team


def _require_mutable_team(
    *,
    application: Application,
    program: PartnerProgram,
) -> None:
    """Разрешает изменение состава только draft-команде до дедлайна."""
    if application.status != Application.STATUS_DRAFT:
        raise ApplicationNotEditableError(
            "Состав команды можно менять только в черновике заявки."
        )
    if program.is_application_deadline_passed():
        raise ApplicationDeadlinePassedError()


def rename_team(*, team: Team, actor: User, name: str) -> Team:
    """Атомарно меняет название draft-команды до дедлайна.

    Операция доступна только текущему капитану и staff. Остальные поля Team
    сервис не принимает и не изменяет.
    """
    with transaction.atomic():
        program, application, team = _lock_team_graph(team)
        if not can_manage_team(actor, team):
            raise TeamManagementPermissionError()
        _require_mutable_team(application=application, program=program)

        team.name = name
        team.save(update_fields=["name", "updated_at"])
        return team


def leave_team(*, team: Team, actor: User) -> TeamMember:
    """Фиксирует выход accepted-участника без удаления истории членства.

    Повторный leave возвращает стабильную team_membership_not_active. Капитан
    обязан сначала передать роль; joined_at при выходе намеренно сохраняется.
    """
    with transaction.atomic():
        program, application, team = _lock_team_graph(team)
        if is_team_captain(actor, team):
            raise CaptainTransferRequiredError()

        member = (
            TeamMember.objects.select_for_update()
            .filter(team=team, user=actor)
            .first()
        )
        if (
            member is None
            or member.role != TeamMember.ROLE_MEMBER
            or member.status != TeamMember.STATUS_ACCEPTED
        ):
            raise TeamMembershipNotActiveError()

        _require_mutable_team(application=application, program=program)
        member.status = TeamMember.STATUS_LEFT
        member.save(update_fields=["status", "updated_at"])
        return member


def remove_team_member(*, team: Team, actor: User, member_id: int) -> TeamMember:
    """Переводит обычного accepted/invited-участника в removed.

    Запись и joined_at сохраняются как история состава. Исторические статусы
    возвращают стабильную team_member_not_removable вместо удаления строки.
    """
    with transaction.atomic():
        program, application, team = _lock_team_graph(team)
        if not can_manage_team(actor, team):
            raise TeamManagementPermissionError()
        _require_mutable_team(application=application, program=program)

        member = (
            TeamMember.objects.select_for_update()
            .filter(team=team, pk=member_id)
            .first()
        )
        if member is None:
            raise TeamMemberNotFoundError()
        if (
            member.role == TeamMember.ROLE_CAPTAIN
            or member.user_id == team.captain_id
        ):
            raise CaptainTransferRequiredError(
                "Капитана нельзя удалить из команды без передачи капитанства."
            )
        if member.status not in {
            TeamMember.STATUS_ACCEPTED,
            TeamMember.STATUS_INVITED,
        }:
            raise TeamMemberNotRemovableError()

        member.status = TeamMember.STATUS_REMOVED
        member.save(update_fields=["status", "updated_at"])
        return member


def transfer_team_captain(
    *,
    team: Team,
    actor: User,
    member_id: int,
) -> Team:
    """Атомарно передает капитанство accepted-участнику draft-команды.

    После общей блокировки Program блокируются Application, Team и обе записи
    TeamMember. Старый капитан сначала становится member, чтобы условная
    уникальность капитана не нарушилась в промежуточном состоянии. Затем вместе
    обновляются Team.captain и Application.user; Application.created_by и Project
    намеренно остаются без изменений.
    """
    with transaction.atomic():
        program, application, team = _lock_team_graph(team)
        if not can_manage_team(actor, team):
            raise TeamManagementPermissionError()
        _require_mutable_team(application=application, program=program)

        locked_members = list(
            TeamMember.objects.select_for_update()
            .select_related("user")
            .filter(team=team)
            .filter(
                models.Q(pk=member_id)
                | models.Q(
                    user_id=team.captain_id,
                    role=TeamMember.ROLE_CAPTAIN,
                    status=TeamMember.STATUS_ACCEPTED,
                )
            )
            .order_by("pk")
        )
        target = next((item for item in locked_members if item.pk == member_id), None)
        captain_members = [
            item
            for item in locked_members
            if item.user_id == team.captain_id
            and item.role == TeamMember.ROLE_CAPTAIN
            and item.status == TeamMember.STATUS_ACCEPTED
        ]

        if team.captain_id != application.user_id:
            raise CaptainMismatchError()
        if len(captain_members) != 1:
            raise CaptainMemberMissingError()
        if target is None:
            raise TeamMemberNotFoundError()
        if (
            target.role != TeamMember.ROLE_MEMBER
            or target.status != TeamMember.STATUS_ACCEPTED
        ):
            raise CaptainTransferTargetInvalidError()
        if not PartnerProgramUserProfile.objects.filter(
            partner_program=program,
            user=target.user,
        ).exists():
            raise TeamMemberRegistrationMissingError(
                "Новый капитан должен быть зарегистрирован на активность."
            )

        require_no_active_conflict(
            program=program,
            user=target.user,
            exclude_application=application,
        )

        old_captain_member = captain_members[0]
        old_captain_member.role = TeamMember.ROLE_MEMBER
        old_captain_member.save(update_fields=["role", "updated_at"])

        application.user = target.user
        application.save(update_fields=["user", "updated_at"])

        team.application = application
        team.captain = target.user
        team.save(update_fields=["captain", "updated_at"])

        target.team = team
        target.role = TeamMember.ROLE_CAPTAIN
        target.save(update_fields=["role", "updated_at"])
        return team
