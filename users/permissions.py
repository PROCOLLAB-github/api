from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAchievementOwnerOrReadOnly(BasePermission):
    """
    Allows access to update only to himself.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or (obj.user == request.user):
            return True
        return False
