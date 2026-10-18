from django.urls import path
from .workspace_views import (
    MyProgramsView,
    AcceptOwnInvitationView,
    PublicInvitationView,
    PublicInvitationActionView,
)

urlpatterns = [
    path("programs/", MyProgramsView.as_view()),
    path(
        "own-invitations/<int:invitation_id>/accept/", AcceptOwnInvitationView.as_view()
    ),
    path("invitations/<str:token>/", PublicInvitationView.as_view()),
    path("invitations/<str:token>/<str:action>/", PublicInvitationActionView.as_view()),
]
