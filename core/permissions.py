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
        # TODO CHECK IF USER IF PROJECT LEADER
        if request.method in SAFE_METHODS or request.user and request.user.id:
            return True
        return False
