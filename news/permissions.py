from django.contrib.auth import get_user_model
from rest_framework import permissions
from rest_framework.exceptions import NotFound
from rest_framework.permissions import SAFE_METHODS

from partner_programs.models import PartnerProgram
from projects.models import Project

User = get_user_model()


class IsNewsCreatorOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        """
        read/update/delete permission
        currently can only be updated/deleted in admin panel
        """
        if request.method in SAFE_METHODS:
            return True
        if (
            isinstance(obj.content_object, Project)
            and obj.content_object.leader == request.user
        ):
            return True
        if isinstance(obj.content_object, User) and obj.content_object == request.user:
            return True
        if isinstance(obj.content_object, PartnerProgram):
            # TODO: implement
            pass
        return False

    def has_permission(self, request, view):
        """
        Creation permission
        Currently can only be created via admin panel
        """
        if request.method in SAFE_METHODS:
            return True

        if view.kwargs.get("project_pk"):
            try:
                project = Project.objects.get(pk=view.kwargs["project_pk"])
                if request.method in SAFE_METHODS or (request.user == project.leader):
                    return True
            except Project.DoesNotExist:
                raise NotFound

        if view.kwargs.get("user_pk"):
            try:
                user = User.objects.get(pk=view.kwargs["user_pk"])
                if request.method in SAFE_METHODS or (request.user == user):
                    return True
            except User.DoesNotExist:
                raise NotFound

        return False
