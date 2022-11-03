from rest_framework.permissions import BasePermission

from core.constants import SAFE_METHODS


class IsStaffOrReadOnly(BasePermission):
    """
    Allows access to update only to staff users.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS or request.user and request.user.is_staff:
            return True
        return False


class IsProjectLeaderOrReadOnly(BasePermission):
    """
    Allows access to update only to project leader.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS or (request.user and request.user.id):
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or (obj.leader == request.user):
            return True
        return False


class IsOwnerOrReadOnly(BasePermission):
    """
    Allows access to update only to himself.
    """

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS or request.user and request.user.id == obj.id:
            return True
        return False
