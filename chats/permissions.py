from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission

from projects.models import Project

User = get_user_model()


def get_lookup_kwarg(request, view, *names):
    view_kwargs = getattr(view, "kwargs", {}) or {}
    parser_kwargs = (getattr(request, "parser_context", None) or {}).get("kwargs", {})

    for name in names:
        if name in view_kwargs:
            return view_kwargs[name]
        if name in parser_kwargs:
            return parser_kwargs[name]
    return None


def is_project_member(user, project) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False

    if project.leader_id == user.id:
        return True

    return project.collaborator_set.filter(user_id=user.id).exists()


class IsProjectChatMember(BasePermission):
    def has_permission(self, request, view) -> bool:
        project_id = get_lookup_kwarg(request, view, "id", "pk")
        if project_id is None:
            return True

        try:
            project = Project.objects.only("id", "leader_id").get(pk=project_id)
        except (Project.DoesNotExist, TypeError, ValueError):
            return False

        return is_project_member(request.user, project)

    def has_object_permission(self, request, view, obj):
        return is_project_member(request.user, obj.project)


class IsChatMember(BasePermission):
    """
    Allows access only to authenticated users.
    """

    def has_permission(self, request, view) -> bool:
        chat_id = get_lookup_kwarg(request, view, "id")
        if chat_id is None:
            return True

        user_id = getattr(request.user, "id", None)
        if user_id is None:
            return False

        return str(user_id) in str(chat_id).split("_")
