from django.db.models import Q, QuerySet

from invites.models import Invite


def get_visible_invites_queryset(user) -> QuerySet[Invite]:
    queryset = Invite.objects.get_invite_for_list_view()

    if not user or not user.is_authenticated:
        return queryset.none()

    if user.is_staff or user.is_superuser:
        return queryset

    return queryset.filter(Q(user_id=user.id) | Q(project__leader_id=user.id))
