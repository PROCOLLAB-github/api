from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAchievementOwnerOrReadOnly(BasePermission):
    """
    Allows access to update only to himself.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS or (
            request.user and request.user.id == request.data.get("user")
        ):
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or (obj.user == request.user):
            return True
        return False