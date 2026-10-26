from django.urls import path

from partner_programs.solution_invitation_api import (
    MySolutionInvitationsView,
    SolutionInvitationActionView,
    SolutionInvitationDetailView,
)

urlpatterns = [
    path("", MySolutionInvitationsView.as_view()),
    path("<int:invitation_id>/", SolutionInvitationDetailView.as_view()),
    path(
        "<int:invitation_id>/accept/",
        SolutionInvitationActionView.as_view(decision="accept"),
    ),
    path(
        "<int:invitation_id>/decline/",
        SolutionInvitationActionView.as_view(decision="decline"),
    ),
]
