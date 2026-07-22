from django.urls import path

from partner_programs.applications_views import (
    ApplicationDetailView,
    ApplicationSubmitView,
    ApplicationWithdrawView,
)
from partner_programs.submission_views import ApplicationSubmissionListCreateView
from partner_programs.team_invite_views import (
    TeamInviteCandidateSearchView,
    TeamInviteListCreateView,
)
from partner_programs.team_views import (
    TeamDetailView,
    TeamLeaveView,
    TeamMemberRemoveView,
    TeamTransferCaptainView,
)

app_name = "applications"

urlpatterns = [
    path(
        "<int:application_id>/team/invite-candidates/",
        TeamInviteCandidateSearchView.as_view(),
        name="team-invite-candidate-search",
    ),
    path(
        "<int:application_id>/team/invites/",
        TeamInviteListCreateView.as_view(),
        name="team-invite-list-create",
    ),
    path(
        "<int:application_id>/team/members/<int:member_id>/remove/",
        TeamMemberRemoveView.as_view(),
        name="team-member-remove",
    ),
    path(
        "<int:application_id>/team/transfer-captain/",
        TeamTransferCaptainView.as_view(),
        name="team-transfer-captain",
    ),
    path(
        "<int:application_id>/team/leave/",
        TeamLeaveView.as_view(),
        name="team-leave",
    ),
    path(
        "<int:application_id>/team/",
        TeamDetailView.as_view(),
        name="team-detail",
    ),
    path(
        "<int:application_id>/submissions/",
        ApplicationSubmissionListCreateView.as_view(),
        name="submission-list-create",
    ),
    path("<int:application_id>/", ApplicationDetailView.as_view(), name="detail"),
    path(
        "<int:application_id>/submit/",
        ApplicationSubmitView.as_view(),
        name="submit",
    ),
    path(
        "<int:application_id>/withdraw/",
        ApplicationWithdrawView.as_view(),
        name="withdraw",
    ),
]
