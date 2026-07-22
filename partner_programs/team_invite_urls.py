from django.urls import path

from partner_programs.team_invite_views import (
    MyTeamInviteListView,
    TeamInviteAcceptView,
    TeamInviteDeclineView,
    TeamInviteRevokeView,
)

app_name = "team_invites"

urlpatterns = [
    path("my/", MyTeamInviteListView.as_view(), name="my-list"),
    path("<int:invite_id>/accept/", TeamInviteAcceptView.as_view(), name="accept"),
    path(
        "<int:invite_id>/decline/",
        TeamInviteDeclineView.as_view(),
        name="decline",
    ),
    path("<int:invite_id>/revoke/", TeamInviteRevokeView.as_view(), name="revoke"),
]
