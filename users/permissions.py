from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, SAFE_METHODS

from users.models import Expert


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
        program_id = view.kwargs.get("program_id")

        if not user.user_type == 3:
            raise PermissionDenied("User is not an expert")
        if not Expert.objects.filter(programs__id=program_id, user=user).exists():
            raise PermissionDenied("You don't have permission to rate this program")
        return True


class IsExpertPost(BasePermission):
    """
    Allows access if user is EXPERT
    """

    def has_permission(self, request, view):
        return True if request.user.user_type == 3 else False
