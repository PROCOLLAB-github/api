from datetime import datetime, timedelta

from django.utils import timezone
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from projects.models import Project


class ProjectVisibilityPermission(BasePermission):
    """
    Ограничивает доступ к непубличным проектам.

    Непубличные проекты доступны:
      - лидеру проекта;
      - администраторам (staff/superuser);
      - участникам команды (collaborators/invites);
      - если проект в программе: менеджерам и экспертам этой программы.
    """

    message = "У вас нет доступа к этому проекту."

    def has_permission(self, request, view):
        project_id = view.kwargs.get("project_pk") or view.kwargs.get("project_id")
        if not project_id and view.__module__.startswith("projects."):
            project_id = view.kwargs.get("id") or view.kwargs.get("pk")

        if not project_id and getattr(getattr(view, "queryset", None), "model", None) is Project:
            project_id = view.kwargs.get("pk")

        if not project_id:
            return True

        try:
            project = Project.objects.only("id", "leader_id", "is_public").get(
                pk=project_id
            )
        except Project.DoesNotExist:
            return True

        return self._can_view_project(request, project)

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, Project):
            project = obj
        else:
            project = getattr(obj, "project", None)
            if project is None:
                return True
        return self._can_view_project(request, project)

    def _can_view_project(self, request, project: Project) -> bool:
        if project.is_public:
            return True

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser or user.is_staff:
            return True

        if project.leader_id == user.id:
            return True

        if project.collaborator_set.filter(user_id=user.id).exists():
            return True

        if project.invite_set.filter(user_id=user.id).exists():
            return True

        return PartnerProgramProject.objects.filter(
            project_id=project.id,
        ).filter(
            Q(partner_program__managers__id=user.id)
            | Q(partner_program__experts__user_id=user.id)
        ).exists()


class IsProjectLeaderOrReadOnlyForNonDrafts(BasePermission):
    """
    Allows access to update only to project leader.
    """

    def has_permission(self, request, view) -> bool:
        # fixme:
        if request.method in SAFE_METHODS or (request.user and request.user.id):
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if (request.method in SAFE_METHODS and not obj.draft) or (
            obj.leader == request.user
            # fixme:
            or obj.collaborator_set.filter(user=request.user).exists()
            or obj.invite_set.filter(user=request.user).exists()
        ):
            return True
        return False


class IsProjectLeader(BasePermission):
    """
    Allows access to get only to project leader.
    """

    def has_permission(self, request, view) -> bool:
        if request.user and request.user.id:
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if obj.leader == request.user:
            return True
        return False


class HasInvolvementInProjectOrReadOnly(BasePermission):
    """
    Allows access to read to everyone involved in the project, and to update only to project leader.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS or (request.user and request.user.id):
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if not obj.draft:
            # not a draft, read-only for everyone, write only for leader
            if (request.method in SAFE_METHODS) or (request.user == obj.leader):
                return True
            return False
        else:
            if (
                request.user == obj.leader
                or obj.collaborator_set.filter(user=request.user).exists()
                or obj.invite_set.filter(user=request.user).exists()
            ):
                return True
            return False


class TimingAfterEndsProgramPermission(BasePermission):
    """
    Forbidden editing/deleting self projects included in programs
    for `_SECONDS_AFTER_CANT_EDIT` seconds -> days from the end of the program.
    If the project is not in program or the request in `SAFE_METHODS` -> allowed.
    """

    _SECONDS_AFTER_CANT_EDIT: int = 60 * 60 * 24 * 30  # Now 30 days.

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True

        program_profile = (
            PartnerProgramUserProfile.objects.filter(user=request.user, project=obj)
            .select_related("partner_program")
            .first()
        )
        moscow_time: datetime = timezone.localtime(timezone.now())

        if program_profile:
            date_from_end_program: timedelta = (
                moscow_time - program_profile.partner_program.datetime_finished
            )
            days_from_end_program: int = date_from_end_program.days
            seconds_from_end_program: int = date_from_end_program.total_seconds()
            if 0 <= seconds_from_end_program <= self._SECONDS_AFTER_CANT_EDIT:
                raise PermissionDenied(
                    detail=self._prepare_exception_detail(
                        days_from_end_program, program_profile
                    )
                )
        return True

    def _prepare_exception_detail(
        self, days_from_end_program: int, program_profile: PartnerProgramUserProfile
    ):
        """
        Prepare response body when `PermissionDenied` exception raised:
            program_name: str -> Program title
            when_can_edit: datetime -> Moskow datetime when user can edit self program
            days_until_resolution: int -> Days when user can edit self program
        """
        datetime_finished: datetime = program_profile.partner_program.datetime_finished
        when_can_edit: datetime = timezone.localtime(
            datetime_finished + timedelta(seconds=self._SECONDS_AFTER_CANT_EDIT)
        )
        days_until_resolution: int = (
            int(self._SECONDS_AFTER_CANT_EDIT / 60 / 60 / 24)
            - days_from_end_program
            - 1
        )
        return {
            "program_name": program_profile.partner_program.name,
            "when_can_edit": when_can_edit,
            "days_until_resolution": days_until_resolution,
        }


class IsNewsAuthorIsProjectLeaderOrReadOnly(BasePermission):
    """
    Allows access to update project news only to leader.
    """

    def has_permission(self, request, view) -> bool:
        try:
            project = Project.objects.get(pk=view.kwargs["project_pk"])
            if request.method in SAFE_METHODS or (request.user == project.leader):
                return True
        except Project.DoesNotExist:
            pass
        return False

    def has_object_permission(self, request, view, obj):
        if (
            request.method in SAFE_METHODS and not obj.project.draft
        ) or obj.project.leader == request.user:
            return True
        return False


class IsProjectLeaderOrReadOnly(BasePermission):
    """
    Читать могут все (в т.ч. анонимы).
    Создавать/изменять/удалять может только лидер проекта.
    """

    message = "Только лидер проекта может создавать, изменять или удалять параметры."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        if not request.user or not request.user.is_authenticated:
            return False

        project_pk = view.kwargs.get("project_pk")
        project_id = project_pk or view.kwargs.get("project_id") or request.data.get("project")
        if not project_id:
            return False

        try:
            project = Project.objects.only("id", "leader_id").get(pk=project_id)
        except Project.DoesNotExist:
            return False

        return project.leader_id == request.user.id

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        return (
            request.user
            and request.user.is_authenticated
            and obj.project.leader_id == request.user.id
        )


class CanBindProjectToProgram(BasePermission):
    message = "Привязать проект к программе может только её участник (или менеджер)."

    def has_permission(self, request, view):
        program_id = (request.data or {}).get("partner_program_id")
        if not program_id:
            return True

        try:
            program = PartnerProgram.objects.get(pk=program_id)
        except PartnerProgram.DoesNotExist:
            raise ValidationError({"partner_program_id": "Программа не найдена."})

        submission_deadline = program.get_project_submission_deadline()
        if submission_deadline and submission_deadline < timezone.now():
            raise ValidationError({"partner_program_id": "Срок подачи проектов в программу завершён."})

        if program.datetime_finished < timezone.now():
            raise ValidationError({"partner_program_id": "Нельзя выбрать завершённую программу."})

        if program.is_manager(request.user):
            return True

        return PartnerProgramUserProfile.objects.filter(
            user=request.user, partner_program=program
        ).exists()
