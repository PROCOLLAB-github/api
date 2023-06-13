from rest_framework.permissions import BasePermission, SAFE_METHODS

from projects.models import Project


class IsProjectLeaderOrReadOnlyForNonDrafts(BasePermission):
    """
    Allows access to update only to project leader.
    """

    def has_permission(self, request, view) -> bool:
        # fixme:
        if request.method in SAFE_METHODS or (request.user and request.user.id):
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if (request.method in SAFE_METHODS and not obj.draft) or (
            obj.leader == request.user
            # fixme:
            or obj.collaborator_set.filter(user=request.user).exists()
            or obj.invite_set.filter(user=request.user).exists()
        ):
            return True
        return False


class IsProjectLeader(BasePermission):
    """
    Allows access to get only to project leader.
    """

    def has_permission(self, request, view) -> bool:
        if request.user and request.user.id:
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if obj.leader == request.user:
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


class IsNewsAuthorIsProjectLeaderOrReadOnly(BasePermission):
    """
    Allows access to update project news only to leader.
    """

    def has_permission(self, request, view) -> bool:
        try:
            project = Project.objects.get(pk=view.kwargs["project_pk"])
            if request.method in SAFE_METHODS or (request.user == project.leader):
                return True
        except Project.DoesNotExist:
            pass
        return False

    def has_object_permission(self, request, view, obj):
        if (
            request.method in SAFE_METHODS and not obj.project.draft
        ) or obj.project.leader == request.user:
            return True
        return False
