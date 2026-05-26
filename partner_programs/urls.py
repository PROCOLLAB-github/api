from django.urls import path

from news.views import NewsDetail, NewsDetailSetLiked, NewsDetailSetViewed, NewsList
from partner_programs.views import (
    ActiveLegalDocumentsView,
    PartnerProgramAcceptOrganizerTermsView,
    PartnerProgramAnalyticsAPIView,
    PartnerProgramAnalyticsContactExportAPIView,
    PartnerProgramAnalyticsExportAPIView,
    PartnerProgramCreateUserAndRegister,
    PartnerProgramDataSchema,
    PartnerProgramDetail,
    PartnerProgramExportProjectsAPIView,
    PartnerProgramExportRatesAPIView,
    PartnerProgramInviteDeleteView,
    PartnerProgramInviteListCreateView,
    PartnerProgramInviteResendView,
    PartnerProgramInviteRevokeView,
    PartnerProgramLegalSettingsView,
    PartnerProgramList,
    PartnerProgramProjectApplyView,
    PartnerProgramProjectsAPIView,
    PartnerProgramProjectSubmitView,
    PartnerProgramReadinessView,
    PartnerProgramRegister,
    PartnerProgramSetLiked,
    PartnerProgramSetViewed,
    PartnerProgramStatsAPIView,
    PartnerProgramSubmitToModerationView,
    PartnerProgramVerificationStatusView,
    PartnerProgramVerificationSubmitView,
    PartnerProgramWithdrawFromModerationView,
    ProgramFiltersAPIView,
    ProgramProjectFilterAPIView,
)

app_name = "partner_programs"

urlpatterns = [
    path(
        "legal-documents/active/",
        ActiveLegalDocumentsView.as_view(),
        name="active-legal-documents",
    ),
    path("", PartnerProgramList.as_view()),
    path("<int:pk>/", PartnerProgramDetail.as_view()),
    path(
        "partner-program-projects/<int:pk>/submit/",
        PartnerProgramProjectSubmitView.as_view(),
        name="partner-program-project-submit",
    ),
    path("<int:pk>/schema/", PartnerProgramDataSchema.as_view()),
    path(
        "<int:pk>/readiness/",
        PartnerProgramReadinessView.as_view(),
        name="partner-program-readiness",
    ),
    path(
        "<int:pk>/stats/",
        PartnerProgramStatsAPIView.as_view(),
        name="partner-program-stats",
    ),
    path(
        "<int:pk>/legal-settings/",
        PartnerProgramLegalSettingsView.as_view(),
        name="partner-program-legal-settings",
    ),
    path(
        "<int:pk>/legal-settings/accept-organizer-terms/",
        PartnerProgramAcceptOrganizerTermsView.as_view(),
        name="partner-program-accept-organizer-terms",
    ),
    path(
        "<int:pk>/submit-to-moderation/",
        PartnerProgramSubmitToModerationView.as_view(),
        name="partner-program-submit-to-moderation",
    ),
    path(
        "<int:pk>/withdraw-from-moderation/",
        PartnerProgramWithdrawFromModerationView.as_view(),
        name="partner-program-withdraw-from-moderation",
    ),
    path("<int:pk>/register/", PartnerProgramRegister.as_view()),
    path("<int:pk>/register_new/", PartnerProgramCreateUserAndRegister.as_view()),
    path(
        "<int:pk>/verification/",
        PartnerProgramVerificationStatusView.as_view(),
        name="program-verification-status",
    ),
    path(
        "<int:pk>/verification/submit/",
        PartnerProgramVerificationSubmitView.as_view(),
        name="program-verification-submit",
    ),
    path(
        "<int:pk>/invites/",
        PartnerProgramInviteListCreateView.as_view(),
        name="program-invites",
    ),
    path(
        "<int:pk>/invites/<int:invite_id>/revoke/",
        PartnerProgramInviteRevokeView.as_view(),
        name="program-invite-revoke",
    ),
    path(
        "<int:pk>/invites/<int:invite_id>/",
        PartnerProgramInviteDeleteView.as_view(),
        name="program-invite-delete",
    ),
    path(
        "<int:pk>/invites/<int:invite_id>/resend/",
        PartnerProgramInviteResendView.as_view(),
        name="program-invite-resend",
    ),
    path("<int:pk>/set_liked/", PartnerProgramSetLiked.as_view()),
    path("<int:pk>/set_viewed/", PartnerProgramSetViewed.as_view()),
    path("<int:partnerprogram_pk>/news/", NewsList.as_view()),
    path("<int:partnerprogram_pk>/news/<int:pk>/", NewsDetail.as_view()),
    path(
        "<int:partnerprogram_pk>/news/<int:pk>/set_viewed/",
        NewsDetailSetViewed.as_view(),
    ),
    path(
        "<int:partnerprogram_pk>/news/<int:pk>/set_liked/", NewsDetailSetLiked.as_view()
    ),
    path("<int:pk>/filters/", ProgramFiltersAPIView.as_view(), name="program-filters"),
    path(
        "<int:pk>/projects/filter/",
        ProgramProjectFilterAPIView.as_view(),
        name="program-projects-filter",
    ),
    path(
        "<int:pk>/projects/",
        PartnerProgramProjectsAPIView.as_view(),
        name="partner-program-projects",
    ),
    path(
        "<int:pk>/analytics/",
        PartnerProgramAnalyticsAPIView.as_view(),
        name="partner-program-analytics",
    ),
    path(
        "<int:pk>/analytics/export/",
        PartnerProgramAnalyticsExportAPIView.as_view(),
        name="partner-program-analytics-export",
    ),
    path(
        "<int:pk>/analytics/contact-export/",
        PartnerProgramAnalyticsContactExportAPIView.as_view(),
        name="partner-program-analytics-contact-export",
    ),
    path(
        "<int:pk>/projects/apply/",
        PartnerProgramProjectApplyView.as_view(),
        name="partner-program-project-apply",
    ),
    path(
        "<int:pk>/export-projects/",
        PartnerProgramExportProjectsAPIView.as_view(),
        name="partner-program-export-projects",
    ),
    path(
        "<int:pk>/export-rates/",
        PartnerProgramExportRatesAPIView.as_view(),
        name="partner-program-export-rates",
    ),
]
