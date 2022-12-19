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
            or obj.collaborator_set.filter(user=request.user).exists()
            or obj.invite_set.filter(user=request.user).exists()
        ):

            return True
        return False


class HasInvolvementInProjectOrReadOnly(BasePermission):
    """
    Allows access to read to everyone involved in the project, and to update only to project leader.
    """

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS or (request.user and request.user.id):
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if not obj.draft:
            # not a draft, read-only for everyone, write only for leader
            if (request.method in SAFE_METHODS) or (request.user == obj.leader):
                return True
            return False
        else:
            if (
                request.user == obj.leader
                or obj.collaborator_set.filter(user=request.user).exists()
                or obj.invite_set.filter(user=request.user).exists()
            ):

                return True
            return False
