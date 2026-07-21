from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from partner_programs.models import (
    Application,
    PartnerProgram,
    PartnerProgramUserProfile,
    Team,
    TeamMember,
)
from projects.models import Project

User = get_user_model()


class ApplicationTeamServiceError(Exception):
    """Базовая ошибка доменного сервиса Application/Team."""

    code = "application_team_error"
    default_detail = "Операция с заявкой недоступна."
    default_field = "non_field_errors"

    def __init__(self, detail=None, *, field=None):
        self.detail = detail or self.default_detail
        self.field = field or self.default_field
        super().__init__(self.detail)


class RegistrationRequiredError(ApplicationTeamServiceError):
    code = "registration_required"
    default_detail = "Сначала зарегистрируйтесь на активность."
    default_field = "registration"


class ApplicationDeadlinePassedError(ApplicationTeamServiceError):
    code = "application_deadline_passed"
    default_detail = "Срок подачи заявок завершен."
    default_field = "datetime_application_ends"


class ParticipationModeNotAllowedError(ApplicationTeamServiceError):
    code = "participation_mode_not_allowed"
    default_detail = "Выбранный формат участия недоступен для этой активности."
    default_field = "participation_mode"


class ParticipationModeUndecidedError(ApplicationTeamServiceError):
    code = "participation_mode_undecided"
    default_detail = "Перед отправкой выберите формат участия."
    default_field = "participation_mode"


class ActiveApplicationConflictError(ApplicationTeamServiceError):
    code = "active_application_conflict"
    default_detail = "Пользователь уже участвует в другой активной заявке."
    default_field = "user"


class TeamRequiredError(ApplicationTeamServiceError):
    code = "team_required"
    default_detail = "Для командной заявки необходимо создать команду."
    default_field = "team"


class TeamNotAllowedError(ApplicationTeamServiceError):
    code = "team_not_allowed"
    default_detail = "Для выбранного формата команда недопустима."
    default_field = "team"


class TeamHasOtherMembersError(ApplicationTeamServiceError):
    code = "team_has_other_members"
    default_detail = "Нельзя сменить формат, пока в команде есть другие участники."
    default_field = "team"


class CaptainMemberMissingError(ApplicationTeamServiceError):
    code = "captain_member_missing"
    default_detail = "В команде отсутствует единственный принятый капитан."
    default_field = "team"


class CaptainMismatchError(ApplicationTeamServiceError):
    code = "captain_mismatch"
    default_detail = "Капитан команды не совпадает с владельцем заявки."
    default_field = "team"


class TeamSizeInvalidError(ApplicationTeamServiceError):
    code = "team_size_invalid"
    default_detail = "Размер команды не соответствует настройкам активности."
    default_field = "team"


class TeamMemberRegistrationMissingError(ApplicationTeamServiceError):
    code = "team_member_registration_missing"
    default_detail = "Не все принятые участники зарегистрированы на активность."
    default_field = "team"


class ApplicationNotEditableError(ApplicationTeamServiceError):
    code = "application_not_editable"
    default_detail = "Заявку нельзя изменить в текущем состоянии."
    default_field = "status"


@dataclass(frozen=True)
class ApplicationCreationResult:
    """Результат idempotent create с признаком новой записи."""

    application: Application
    created: bool


def _lock_program(program: PartnerProgram) -> PartnerProgram:
    # Одна строка Program служит общей точкой сериализации cross-table проверок
    # Application и TeamMember внутри этого service.
    return PartnerProgram.objects.select_for_update().get(pk=program.pk)


def _lock_application(application: Application) -> Application:
    return (
        Application.objects.select_for_update()
        .select_related("program", "user", "created_by", "project")
        .get(pk=application.pk)
    )


def _require_registration(*, program: PartnerProgram, user: User) -> None:
    if user is None or not PartnerProgramUserProfile.objects.filter(
        partner_program=program,
        user=user,
    ).exists():
        raise RegistrationRequiredError()


def _require_open_application_deadline(program: PartnerProgram) -> None:
    if program.is_application_deadline_passed():
        raise ApplicationDeadlinePassedError()


def _validate_participation_mode(
    *,
    program: PartnerProgram,
    participation_mode: str,
    allow_undecided: bool,
) -> None:
    known_modes = {value for value, _label in Application.PARTICIPATION_MODE_CHOICES}
    if participation_mode not in known_modes:
        raise ParticipationModeNotAllowedError()
    if participation_mode == Application.PARTICIPATION_MODE_UNDECIDED:
        if allow_undecided:
            return
        raise ParticipationModeUndecidedError()
    if not program.allows_participation_mode(participation_mode):
        raise ParticipationModeNotAllowedError()


def _active_application_ids_for_user(
    *,
    program: PartnerProgram,
    user: User,
) -> set[int]:
    owned_ids = Application.objects.filter(
        program=program,
        user=user,
        status__in=Application.ACTIVE_STATUSES,
    ).values_list("pk", flat=True)
    membership_ids = TeamMember.objects.select_for_update().filter(
        user=user,
        status=TeamMember.STATUS_ACCEPTED,
        team__application__program=program,
        team__application__status__in=Application.ACTIVE_STATUSES,
    ).values_list("team__application_id", flat=True)
    return set(owned_ids).union(membership_ids)


def _require_no_active_conflict(
    *,
    program: PartnerProgram,
    user: User,
    exclude_application: Application | None = None,
) -> None:
    conflict_ids = _active_application_ids_for_user(program=program, user=user)
    if exclude_application is not None:
        conflict_ids.discard(exclude_application.pk)
    if not conflict_ids:
        return

    # Блокируем найденные Application после общей блокировки Program, чтобы
    # последовательные domain-операции не приняли решения по устаревшим данным.
    if Application.objects.select_for_update().filter(pk__in=conflict_ids).exists():
        raise ActiveApplicationConflictError()


def _create_team_with_captain(
    *,
    application: Application,
    team_name: str | None,
) -> Team:
    team = Team.objects.create(
        application=application,
        captain=application.user,
        name=team_name or "",
    )
    TeamMember.objects.create(
        team=team,
        user=application.user,
        role=TeamMember.ROLE_CAPTAIN,
        status=TeamMember.STATUS_ACCEPTED,
        invited_by=None,
    )
    return team


def _existing_application_is_compatible(
    *,
    application: Application,
    participation_mode: str,
    form_data: dict | None,
    project: Project | None,
    team_name: str | None,
) -> bool:
    if application.participation_mode != participation_mode:
        return False
    if form_data is not None and application.form_data != form_data:
        return False
    if project is not None and application.project_id != project.pk:
        return False
    if participation_mode == Application.PARTICIPATION_MODE_TEAM:
        team = Team.objects.select_for_update().filter(application=application).first()
        if team is None:
            raise TeamRequiredError()
        _require_valid_captain_member(application=application, team=team)
        if team_name is not None and team.name != team_name:
            return False
    elif team_name:
        raise TeamNotAllowedError()
    return True


def create_or_get_application(
    *,
    program: PartnerProgram,
    user: User,
    created_by: User,
    participation_mode: str,
    form_data: dict | None = None,
    project: Project | None = None,
    team_name: str | None = None,
) -> ApplicationCreationResult:
    """Создает draft Application или возвращает совместимую активную заявку.

    Аргументы описывают Program, владельца/автора, формат и начальные данные.
    Возвращает ApplicationCreationResult с признаком создания. Может выбросить
    ApplicationTeamServiceError при отсутствии Registration, закрытом дедлайне,
    конфликте участия или несовместимой policy. Операция атомарна: для team
    Application, Team и accepted-капитан либо создаются вместе, либо полностью
    откатываются.
    """
    with transaction.atomic():
        program = _lock_program(program)
        _require_registration(program=program, user=user)
        _require_open_application_deadline(program)
        _validate_participation_mode(
            program=program,
            participation_mode=participation_mode,
            allow_undecided=True,
        )

        existing_application = (
            Application.objects.select_for_update()
            .filter(
                program=program,
                user=user,
                status__in=Application.ACTIVE_STATUSES,
            )
            .order_by("-created_at")
            .first()
        )
        _require_no_active_conflict(
            program=program,
            user=user,
            exclude_application=existing_application,
        )
        if existing_application is not None:
            if not _existing_application_is_compatible(
                application=existing_application,
                participation_mode=participation_mode,
                form_data=form_data,
                project=project,
                team_name=team_name,
            ):
                raise ActiveApplicationConflictError(
                    "Активная заявка несовместима с повторным запросом."
                )
            return ApplicationCreationResult(existing_application, created=False)

        if participation_mode != Application.PARTICIPATION_MODE_TEAM and team_name:
            raise TeamNotAllowedError()

        try:
            application = Application.objects.create(
                program=program,
                user=user,
                created_by=created_by,
                participation_mode=participation_mode,
                form_data={} if form_data is None else form_data,
                project=project,
                status=Application.STATUS_DRAFT,
            )
        except IntegrityError as exc:
            raise ActiveApplicationConflictError() from exc

        if participation_mode == Application.PARTICIPATION_MODE_TEAM:
            _create_team_with_captain(
                application=application,
                team_name=team_name,
            )

        return ApplicationCreationResult(application, created=True)


def _locked_team(application: Application) -> Team | None:
    return (
        Team.objects.select_for_update()
        .select_related("application", "captain")
        .filter(application=application)
        .first()
    )


def _require_valid_captain_member(*, application: Application, team: Team) -> None:
    if team.application_id != application.pk or team.captain_id != application.user_id:
        raise CaptainMismatchError()

    captain_members = list(
        TeamMember.objects.filter(
            team=team,
            role=TeamMember.ROLE_CAPTAIN,
            status=TeamMember.STATUS_ACCEPTED,
        )
    )
    if len(captain_members) != 1:
        raise CaptainMemberMissingError()
    if captain_members[0].user_id != team.captain_id:
        raise CaptainMismatchError()


def change_application_participation_mode(
    *,
    application: Application,
    actor: User,
    participation_mode: str,
    team_name: str | None = None,
) -> Application:
    """Меняет формат draft Application и синхронно управляет базовой Team.

    Принимает заявку, владельца-actor, новый формат и необязательное название
    команды. Возвращает обновленную Application. Может выбросить доменные
    ошибки доступа, Registration, deadline, policy, конфликта или структуры
    Team. Транзакция гарантирует атомарное создание/удаление Team и капитана;
    переход team → individual разрешен только для команды без других записей.
    """
    with transaction.atomic():
        program = _lock_program(application.program)
        application = _lock_application(application)
        if application.user_id != actor.pk:
            raise ApplicationNotEditableError(
                "Только владелец может изменить формат заявки."
            )
        if application.status != Application.STATUS_DRAFT:
            raise ApplicationNotEditableError()

        _require_registration(program=program, user=application.user)
        _require_open_application_deadline(program)
        _validate_participation_mode(
            program=program,
            participation_mode=participation_mode,
            allow_undecided=True,
        )
        _require_no_active_conflict(
            program=program,
            user=application.user,
            exclude_application=application,
        )

        current_mode = application.participation_mode
        team = _locked_team(application)

        if current_mode == participation_mode:
            if current_mode == Application.PARTICIPATION_MODE_TEAM:
                if team is None:
                    raise TeamRequiredError()
                _require_valid_captain_member(application=application, team=team)
                if team_name is not None and team.name != team_name:
                    team.name = team_name
                    team.save(update_fields=["name", "updated_at"])
            elif team is not None:
                raise TeamNotAllowedError()
            elif team_name:
                raise TeamNotAllowedError()
            return application

        if current_mode == Application.PARTICIPATION_MODE_TEAM:
            if team is None:
                raise TeamRequiredError()
            _require_valid_captain_member(application=application, team=team)
            if participation_mode == Application.PARTICIPATION_MODE_UNDECIDED:
                raise TeamNotAllowedError(
                    "Командную заявку нельзя вернуть в неопределенный формат."
                )
            if participation_mode == Application.PARTICIPATION_MODE_INDIVIDUAL:
                # Любая дополнительная запись сохраняет историю состава, поэтому
                # team → individual допустим только для единственного капитана.
                if team.members.exclude(
                    role=TeamMember.ROLE_CAPTAIN,
                    user=team.captain,
                ).exists():
                    raise TeamHasOtherMembersError()
                team.delete()
                team = None
        elif team is not None:
            raise TeamNotAllowedError()

        if participation_mode == Application.PARTICIPATION_MODE_TEAM:
            application.participation_mode = participation_mode
            application.save(update_fields=["participation_mode", "updated_at"])
            _create_team_with_captain(
                application=application,
                team_name=team_name,
            )
            return application

        if team_name:
            raise TeamNotAllowedError()
        application.participation_mode = participation_mode
        application.save(update_fields=["participation_mode", "updated_at"])
        return application


def validate_team_invariants(application: Application) -> None:
    """Проверяет полный invariant Team, не изменяя Application или команду.

    Для individual требует отсутствие Team, для undecided запрещает submit, а
    для team проверяет капитана, Registration accepted-участников и границы
    размера из Program policy. Возвращаемого значения нет; нарушение выражается
    специализированной ApplicationTeamServiceError.
    """
    if application.participation_mode == Application.PARTICIPATION_MODE_UNDECIDED:
        raise ParticipationModeUndecidedError()

    team = Team.objects.select_related("application", "captain").filter(
        application=application
    ).first()
    if application.participation_mode == Application.PARTICIPATION_MODE_INDIVIDUAL:
        if team is not None:
            raise TeamNotAllowedError()
        return
    if application.participation_mode != Application.PARTICIPATION_MODE_TEAM:
        raise ParticipationModeNotAllowedError()
    if team is None:
        raise TeamRequiredError()

    _require_valid_captain_member(application=application, team=team)
    # Invited/declined/removed/left сохраняют историю, но участниками команды
    # при submit считаются только accepted-записи, включая капитана.
    accepted_members = list(
        TeamMember.objects.filter(team=team, status=TeamMember.STATUS_ACCEPTED)
        .select_related("user")
    )
    accepted_user_ids = {member.user_id for member in accepted_members}
    registered_user_ids = set(
        PartnerProgramUserProfile.objects.filter(
            partner_program=application.program,
            user_id__in=accepted_user_ids,
        ).values_list("user_id", flat=True)
    )
    if accepted_user_ids != registered_user_ids:
        raise TeamMemberRegistrationMissingError()

    accepted_count = len(accepted_members)
    minimum = application.program.team_min_size
    maximum = application.program.team_max_size
    if (
        minimum is None
        or maximum is None
        or accepted_count < minimum
        or accepted_count > maximum
    ):
        raise TeamSizeInvalidError()


def _require_no_team_member_conflicts(application: Application) -> None:
    if application.participation_mode == Application.PARTICIPATION_MODE_TEAM:
        user_ids = TeamMember.objects.filter(
            team__application=application,
            status=TeamMember.STATUS_ACCEPTED,
        ).values_list("user_id", flat=True)
    else:
        user_ids = [application.user_id]

    for user_id in user_ids:
        _require_no_active_conflict(
            program=application.program,
            user=User.objects.get(pk=user_id),
            exclude_application=application,
        )


def submit_application(*, application: Application, actor: User) -> Application:
    """Валидирует и атомарно отправляет Application.

    Принимает заявку и actor; владельцу и staff сохраняет текущий contract
    доступа. Возвращает submitted Application. Повторный submit идемпотентен и
    не меняет submitted_at даже после deadline. Для draft возможны доменные
    ошибки Registration, deadline, policy, конфликта или Team invariant. Все
    проверки и переход выполняются в одной транзакции.
    """
    with transaction.atomic():
        program = _lock_program(application.program)
        application = _lock_application(application)
        if application.user_id != actor.pk and not (
            actor.is_staff or actor.is_superuser
        ):
            raise ApplicationNotEditableError(
                "Только владелец или staff может отправить заявку."
            )

        # Идемпотентный повтор не зависит от изменившегося deadline и не должен
        # повторно записывать submitted_at.
        if application.status == Application.STATUS_SUBMITTED:
            return application
        if application.status != Application.STATUS_DRAFT:
            raise ApplicationNotEditableError(
                "Отправить можно только черновик заявки."
            )

        _require_registration(program=program, user=application.user)
        _require_open_application_deadline(program)
        _validate_participation_mode(
            program=program,
            participation_mode=application.participation_mode,
            allow_undecided=False,
        )
        validate_team_invariants(application)
        _require_no_team_member_conflicts(application)

        application.status = Application.STATUS_SUBMITTED
        application.submitted_at = timezone.now()
        application.save(update_fields=["status", "submitted_at", "updated_at"])
        return application
