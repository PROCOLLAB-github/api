from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission

from projects.models import Project

User = get_user_model()


class IsProjectChatMember(BasePermission):
    def has_permission(self, request, view) -> bool:
        try:
            project = Project.objects.get(pk=view.kwargs["pk"])
        except Project.DoesNotExist:
            return False
        if request.user in project.get_collaborators_user_list():
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if request.user in obj.project.get_collaborators_user_list():
            return True
        return False
