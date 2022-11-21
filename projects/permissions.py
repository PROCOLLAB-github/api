from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsProjectLeaderOrReadOnlyForNonDrafts(BasePermission):
    """
    Allows access to update only to project leader.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS or (request.user and request.user.id):
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if (request.method in SAFE_METHODS and not obj.draft) or (
            obj.leader == request.user
        ):
            return True
        return False
