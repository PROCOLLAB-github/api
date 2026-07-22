from rest_framework.permissions import BasePermission

from partner_programs.models import Application, PartnerProgram, Submission, Team, TeamMember


def _is_authenticated(user) -> bool:
    return bool(user and user.is_authenticated)


def _is_staff(user) -> bool:
    return _is_authenticated(user) and bool(user.is_staff or user.is_superuser)


def is_application_owner(user, application: Application) -> bool:
    """Проверяет, является ли пользователь текущим владельцем заявки."""
    return _is_authenticated(user) and application.user_id == user.pk


def is_team_captain(user, team: Team) -> bool:
    """Проверяет, является ли пользователь текущим капитаном команды."""
    return _is_authenticated(user) and team.captain_id == user.pk


def is_accepted_team_member(user, team: Team) -> bool:
    """Учитывает только активное принятое членство, а не историю состава."""
    if not _is_authenticated(user):
        return False
    return TeamMember.objects.filter(
        team=team,
        user=user,
        status=TeamMember.STATUS_ACCEPTED,
    ).exists()


def is_program_manager(user, program: PartnerProgram) -> bool:
    """Проверяет membership пользователя в managers конкретной программы."""
    return _is_authenticated(user) and program.is_manager(user)


def can_view_application(user, application: Application) -> bool:
    """Разрешает чтение владельцу, accepted-команде, менеджеру и staff."""
    if _is_staff(user) or is_application_owner(user, application):
        return True
    if is_program_manager(user, application.program):
        return True
    try:
        team = application.team
    except Team.DoesNotExist:
        return False
    return is_accepted_team_member(user, team)


def can_edit_application(user, application: Application) -> bool:
    """Ограничивает изменения владельцем/капитаном и staff."""
    return _is_staff(user) or is_application_owner(user, application)


def can_view_team(user, team: Team) -> bool:
    """Разрешает чтение accepted-составу, менеджеру программы и staff."""
    return (
        _is_staff(user)
        or is_program_manager(user, team.application.program)
        or is_accepted_team_member(user, team)
    )


def can_manage_team(user, team: Team) -> bool:
    """Ограничивает управление текущим капитаном и staff."""
    return _is_staff(user) or is_team_captain(user, team)


def can_view_submission(user, submission: Submission) -> bool:
    """Наследует read-доступ Submission от связанной Application."""
    return can_view_application(user, submission.application)


def can_edit_submission(user, submission: Submission) -> bool:
    """Оставляет mutation Submission владельцу заявки и staff."""
    return can_edit_application(user, submission.application)


class IsProjectLeader(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.project.leader == request.user


class IsExpertOrManagerOfProgram(BasePermission):
    """
    Доступ разрешён только экспертам и менеджерам конкретной программы.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        program_id = view.kwargs.get("pk")
        if not program_id:
            return False

        try:
            program = PartnerProgram.objects.get(pk=program_id)
        except PartnerProgram.DoesNotExist:
            return False

        if program.is_manager(request.user):
            return True

        return program.experts.filter(user=request.user).exists()


class IsAdminOrManagerOfProgram(BasePermission):
    """
    Доступ разрешён только админам и менеджерам конкретной программы.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        program_id = view.kwargs.get("pk") or view.kwargs.get("program_id")
        if not program_id:
            return False

        try:
            program = PartnerProgram.objects.get(pk=program_id)
        except PartnerProgram.DoesNotExist:
            return False

        return program.is_manager(user)
