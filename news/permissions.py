from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.permissions import SAFE_METHODS

from partner_programs.models import PartnerProgram
from projects.models import Project

User = get_user_model()


class IsNewsCreatorOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        if view.kwargs.get("project_pk"):
            project = get_object_or_404(Project, pk=view.kwargs["project_pk"])
            return request.user == project.leader

        if view.kwargs.get("user_pk"):
            user = get_object_or_404(User, pk=view.kwargs["user_pk"])
            return request.user == user

        if view.kwargs.get("partnerprogram_pk"):
            program = get_object_or_404(
                PartnerProgram, pk=view.kwargs["partnerprogram_pk"]
            )
            return program.is_manager(request.user)

        return False

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        if isinstance(obj.content_object, Project):
            return obj.content_object.leader == request.user

        if isinstance(obj.content_object, User):
            return obj.content_object == request.user

        if isinstance(obj.content_object, PartnerProgram):
            return obj.content_object.is_manager(request.user)

        return False
