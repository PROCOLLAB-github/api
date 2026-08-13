from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsVacancyResponseOwnerOrReadOnly(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or obj.user == request.user:
            return True
        return False


class IsVacancyProjectLeader(BasePermission):
    """Разрешает изменение вакансии руководителю проекта и администрации."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if (
            obj.project.leader == user
            or getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
        ):
            return True
        return False


class IsProjectLeaderForVacancyResponse(BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if (
            obj.vacancy.project.leader == user
            or getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
        ):
            return True
        return False
