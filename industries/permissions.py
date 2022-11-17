from rest_framework.permissions import BasePermission, SAFE_METHODS


class IndustryPermission(BasePermission):
    """
    Allows access to update only to staff users.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS or request.user and request.user.is_staff:
            return True
        return False

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS or request.user and request.user.is_staff:
            return True
        return False
