from functools import wraps

from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission, SAFE_METHODS

from partner_programs.models import PartnerProgram

PROGRAM_CREATION_PERMISSION = "partner_programs.add_partnerprogram"


def can_create_program(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and user.has_perm(PROGRAM_CREATION_PERMISSION)
    )


def require_create_program(user):
    if not can_create_program(user):
        raise PermissionDenied("Администратор еще не выдал вам право создания программ.")


class CanCreateProgram(BasePermission):
    def has_permission(self, request, view):
        require_create_program(request.user)
        return True


class ProgramDraftVisibility(BasePermission):
    """One boundary for every program route, after DRF authentication."""

    def has_permission(self, request, view):
        from partner_programs.models import PartnerProgramProject

        if "partner-program-projects/" in request.path:
            link = (
                PartnerProgramProject.objects.select_related("partner_program", "project")
                .filter(pk=view.kwargs.get("pk"))
                .first()
            )
            view.visibility_program_link = link
            program = link.partner_program if link else None
        else:
            pk = view.kwargs.get("partnerprogram_pk") or view.kwargs.get("pk")
            program = PartnerProgram.objects.filter(pk=pk).first() if pk else None
        # Reuse this read in read-only views, never for transactional writes.
        view.visibility_program = program
        if program is None or not program.draft:
            return True
        setattr(getattr(request, "_request", request), "_program_draft_response", True)
        if not can_manage_program(request.user, program):
            raise NotFound()
        if request.method not in SAFE_METHODS and not (
            "/management/" in request.path or "/news/" in request.path
        ):
            # Previewing a draft never enrolls, views, likes or creates a solution.
            raise NotFound()
        return True


def program_view(view_class, **kwargs):
    view = view_class.as_view(
        permission_classes=[ProgramDraftVisibility, *view_class.permission_classes],
        **kwargs,
    )

    @wraps(view)
    def dispatch(request, *args, **view_kwargs):
        response = view(request, *args, **view_kwargs)
        if getattr(request, "_program_draft_response", False):
            response["Cache-Control"] = "private, no-store"
        return response

    return dispatch


def can_manage_program(user, program: PartnerProgram) -> bool:
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    return program.is_manager(user)


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


class IsAdminManagerOrExpertOfProgram(BasePermission):
    """Allow administrators, managers, and experts of one program."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        program_id = view.kwargs.get("pk") or view.kwargs.get("program_id")
        if not program_id:
            return False

        try:
            program = PartnerProgram.objects.get(pk=program_id)
        except PartnerProgram.DoesNotExist:
            return False

        return (
            can_manage_program(user, program)
            or program.experts.filter(user=user).exists()
        )


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

        return can_manage_program(user, program)
