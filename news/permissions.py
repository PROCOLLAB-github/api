from rest_framework import permissions
from rest_framework.permissions import SAFE_METHODS

from projects.models import Project


class IsNewsCreatorOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        """
        read/update/delete permission
        currently can only be updated/deleted in admin panel
        """
        if request.method in SAFE_METHODS:
            return True
        if isinstance(obj.content_object, Project):
            # it's a project
            if obj.content_object.leader == request.user:
                return True
        else:
            # it's a partner program
            # TODO: implement
            pass
        return False

    def has_permission(self, request, view):
        """
        Creation permission
        Currently can only be created via admin panel
        """
        # everybody can read this
        if request.method in SAFE_METHODS:
            return True

        try:
            # try to judge it as a project
            project = Project.objects.get(pk=view.kwargs["project_pk"])
            if request.method in SAFE_METHODS or (request.user == project.leader):
                return True
        except Project.DoesNotExist:
            return False
        except KeyError:
            # It's a partner program, currently can only be created via admin
            # TODO: implement
            pass
        return False
