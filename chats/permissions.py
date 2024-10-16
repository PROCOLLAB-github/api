from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission

from projects.models import Project

User = get_user_model()


class IsProjectChatMember(BasePermission):
    def has_permission(self, request, view) -> bool:
        try:
            project = Project.objects.get(pk=view.kwargs["id"])
        except Project.DoesNotExist:
            return False
        if request.user in project.get_collaborators_user_list():
            return True
        return True

    def has_object_permission(self, request, view, obj):
        if request.user in obj.project.get_collaborators_user_list():
            return True
        return False


class IsChatMember(BasePermission):
    """
    Allows access only to authenticated users.
    """

    def has_permission(self, request, view):
        kwargs = request.parser_context.get("kwargs")

        chat_id: str = kwargs["id"]

        return str(request.user.id) in chat_id
