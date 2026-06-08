from rest_framework.permissions import BasePermission, SAFE_METHODS


def can_view_invite(user, invite) -> bool:
    if not user or not user.is_authenticated:
        return False

    return (
        user.is_staff
        or user.is_superuser
        or invite.user_id == user.id
        or invite.project.leader_id == user.id
    )


def can_manage_invite(user, invite) -> bool:
    if not user or not user.is_authenticated:
        return False

    return invite.project.leader_id == user.id


def can_decide_invite(user, invite) -> bool:
    if not user or not user.is_authenticated:
        return False

    return invite.user_id == user.id


class InviteDetailPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return can_view_invite(request.user, obj)

        return can_manage_invite(request.user, obj)


class InviteDecisionPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return can_decide_invite(request.user, obj)
