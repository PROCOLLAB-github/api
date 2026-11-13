from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, SAFE_METHODS

from project_rates.program_experts import can_evaluate_program, has_evaluation_role


class IsAchievementOwnerOrReadOnly(BasePermission):
    """
    Allows access to update only to himself.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or (obj.user == request.user):
            return True
        return False


class IsExpert(BasePermission):
    """
    Allows access if user is EXPERT
    """

    def has_permission(self, request, view):
        user = request.user
        if not getattr(user, "is_authenticated", False):
            raise PermissionDenied("Authentication credentials were not provided.")
        program_id = view.kwargs.get("program_id")

        if not can_evaluate_program(user, program_id):
            raise PermissionDenied("Оценивание доступно экспертам этой программы.")
        return True


class IsExpertPost(BasePermission):
    """
    Allows access if user is EXPERT
    """

    def has_permission(self, request, view):
        user = request.user
        if not getattr(user, "is_authenticated", False):
            raise PermissionDenied("Authentication credentials were not provided.")
        if not has_evaluation_role(user):
            raise PermissionDenied("Оценивание доступно экспертам программы.")
        return True


class CustomIsAuthenticated(BasePermission):
    def has_permission(self, request, view):
        if (
            hasattr(view, "authentication_off") and view.authentication_off
        ):  # Проверка наличия и значения атрибута
            return True
        return bool(request.user and request.user.is_authenticated)
