from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsStaffOrReadOnly(BasePermission):
    """
    Allows access to update only to staff users.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS or request.user and request.user.is_staff:
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


class IsMessageOwner(BasePermission):
    """
    Allows access to update only to himself.
    """

    def has_object_permission(self, request, view, obj) -> bool:
        if request.user and request.user.id == obj.author.id:
            return True
        return False


class IsUserInChat(BasePermission):
    """
    Allows access to update only to himself.
    """

    def has_object_permission(self, request, view, obj) -> bool:
        if request.user in obj.chat.users.all():
            return True
        return False
