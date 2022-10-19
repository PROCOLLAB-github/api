from rest_framework.permissions import BasePermission

SAFE_METHODS = ["GET", "HEAD", "OPTIONS"]


class IsStaffOrReadOnly(BasePermission):
    """
    Allows access only to staff users.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS or request.user and request.user.is_staff:
            return True
        return False
