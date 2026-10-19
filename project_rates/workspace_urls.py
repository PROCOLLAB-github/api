from django.urls import path
from .notifications import ExpertNotificationsView
from .workspace_views import (
    MyProgramsView,
    AcceptOwnInvitationView,
    PublicInvitationView,
    PublicInvitationActionView,
)

urlpatterns = [
    path("notifications/", ExpertNotificationsView.as_view()),
    path("notifications/<int:notification_id>/read/", ExpertNotificationsView.as_view()),
    path("programs/", MyProgramsView.as_view()),
    path(
        "own-invitations/<int:invitation_id>/accept/", AcceptOwnInvitationView.as_view()
    ),
    path("invitations/<str:token>/", PublicInvitationView.as_view()),
    path("invitations/<str:token>/<str:action>/", PublicInvitationActionView.as_view()),
]
