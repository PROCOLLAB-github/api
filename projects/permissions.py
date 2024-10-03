from datetime import timedelta, datetime

from django.utils import timezone

from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.exceptions import PermissionDenied

from projects.models import Project
from partner_programs.models import PartnerProgramUserProfile


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
            PartnerProgramUserProfile.objects
            .filter(user=request.user, project=obj)
            .select_related("partner_program")
            .first()
        )
        moscow_time: datetime = timezone.localtime(timezone.now())

        if program_profile:
            date_from_end_program: timedelta = (moscow_time - program_profile.partner_program.datetime_finished)
            days_from_end_program: int = date_from_end_program.days
            seconds_from_end_program: int = date_from_end_program.total_seconds()
            if 0 <= seconds_from_end_program <= self._SECONDS_AFTER_CANT_EDIT:
                raise PermissionDenied(detail=self._prepare_exception_detail(days_from_end_program, program_profile))
        return True

    def _prepare_exception_detail(self, days_from_end_program: int, program_profile: PartnerProgramUserProfile):
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
        days_until_resolution: int = int(self._SECONDS_AFTER_CANT_EDIT / 60 / 60 / 24) - days_from_end_program - 1
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
