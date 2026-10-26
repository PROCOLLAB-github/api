from django.urls import path

from partner_programs.solution_action_api import SolutionActionView
from partner_programs.solution_case_action_api import SolutionCaseChangeView
from partner_programs.solution_history_api import SolutionHistoryView
from partner_programs.solution_member_action_api import SolutionMemberRemovalView
from partner_programs.solution_archive_action_api import SolutionArchiveView
from partner_programs.solution_registration_action_api import (
    SolutionRegistrationRemovalView,
    SolutionRegistrationRemovalHistoryView,
)
from partner_programs.solution_publication_api import (
    PublishedSolutionListView,
    PublishedSolutionDetailView,
)
from partner_programs.solution_attention_api import SolutionExpertReminderView
from partner_programs.solution_analytics_api import (
    SolutionCaseAnalyticsView,
    SolutionManagerAnalyticsView,
    SolutionManagerAssignmentsView,
    SolutionManagerAssignmentView,
    SolutionManagerSolutionsView,
    SolutionManagerExportView,
)
from project_rates.solution_evaluation_api import (
    SolutionRatingsView,
    SolutionRatingView,
    SolutionExpertAssignmentsView,
    SolutionAllocationView,
    SolutionAllocationApplyView,
    SolutionQuotaView,
    SolutionResultsView,
    SolutionResultsExportView,
)
from partner_programs.solution_submission_api import SolutionSubmitView
from partner_programs.solution_form_api import ManagedSolutionFormView, SolutionFormView
from partner_programs.solution_invitation_api import SolutionInvitationsView
from partner_programs.solution_api import (
    SolutionCaptainView,
    SolutionContextView,
    SolutionDetailView,
    SolutionLeaveView,
    SolutionListCreateView,
    SolutionMemberView,
)
from partner_programs.attention_views import AttentionActionView
from partner_programs.report_views import ProgramReportView
from partner_programs.registration_views import (
    RegistrationSettingsView,
    RegistrationPublishView,
    RegistrationImportView,
    RegistrationConnectionView,
    PublicRegistrationView,
    PublicRegistrationActionView,
)
from partner_programs.organizer_views import (
    OrganizersView,
    OrganizerAccessView,
    OrganizerInvitationActionView,
    PublicOrganizerInvitationView,
    PublicOrganizerInvitationActionView,
)

from news.views import NewsDetail, NewsDetailSetLiked, NewsDetailSetViewed, NewsList
from partner_programs.views import (
    PartnerProgramCreateUserAndRegister,
    PartnerProgramDataSchema,
    PartnerProgramDetail,
    PartnerProgramExportProjectsAPIView,
    PartnerProgramExportRatesAPIView,
    PartnerProgramList,
    ProgramManagerAnalyticsAPIView,
    ProgramManagerAssignmentsAPIView,
    ProgramManagerAssignmentScoresAPIView,
    ProgramManagerParticipantsWithoutTeamAPIView,
    ProgramManagerParticipantsWithoutOnboardingAPIView,
    ProgramManagerParticipantsWithoutVisitAPIView,
    ProgramManagerProjectsAwaitingEvaluationAPIView,
    ProgramManagerProjectsNotSubmittedAPIView,
    PartnerProgramProjectApplyView,
    PartnerProgramProjectsAPIView,
    PartnerProgramProjectSubmitView,
    PartnerProgramProjectFieldsView,
    PartnerProgramRegister,
    PartnerProgramSetLiked,
    PartnerProgramSetViewed,
    PartnerProgramWelcomeAcknowledgement,
    ProgramFiltersAPIView,
    ProgramProjectFilterAPIView,
)

from partner_programs.widget_views import ProgramRoleWidgetAPIView

from partner_programs.management_views import (
    ManagementView,
    ManagementProjectFormView,
    ManagementCriteriaView,
    ManagementParticipantsView,
    ManagementParticipantsExportView,
    ManagementSelectionView,
    ManagementParticipantsRemovalPreviewView,
    ManagementParticipantsRemovalView,
    ManagementProjectsView,
    ManagementProjectsExportView,
    ManagementProjectActionPreviewView,
    ManagementProjectActionApplyView,
    ManagementTeamView,
    ManagementEvaluationView,
    ManagementSettingsView,
    ManagementMaterialsView,
    ManagementMaterialDetailView,
)

from project_rates.workspace_views import (
    ExpertsView,
    ExpertsBulkView,
    InvitationActionView,
    ExpertAssignmentsView,
    ExpertCaseScopeView,
    ProjectExpertsView,
    AllocationView,
    AllocationApplyView,
    EvaluatorsView,
)

from partner_programs.results_views import (
    ManagementResultsView,
    ManagementResultsExportView,
)

from partner_programs.certificate_views import (
    CertificateSettingsView,
    CertificateAssetView,
    CertificatePreviewView,
    CertificateTestView,
    CertificateActivateView,
    CertificateQueueView,
    CertificateJournalView,
    CertificateRetryView,
    CertificateSelectionView,
    CertificateDownloadView,
    CertificateArchiveView,
    MyCertificatesView,
    PublicCertificateDownloadView,
)

app_name = "partner_programs"

urlpatterns = [
    path("<int:pk>/published-solutions/", PublishedSolutionListView.as_view()),
    path(
        "<int:pk>/published-solutions/<int:solution_id>/",
        PublishedSolutionDetailView.as_view(),
    ),
    path(
        "<int:pk>/management/solution-analytics/attention/solutions-awaiting-evaluation/reminder-preview/",
        SolutionExpertReminderView.as_view(),
    ),
    path(
        "<int:pk>/management/solution-analytics/attention/solutions-awaiting-evaluation/reminders/",
        SolutionExpertReminderView.as_view(reminder_action="confirm"),
    ),
    path(
        "<int:pk>/management/solution-analytics/", SolutionManagerAnalyticsView.as_view()
    ),
    path(
        "<int:pk>/management/solution-analytics/assignments/",
        SolutionManagerAssignmentsView.as_view(),
    ),
    path(
        "<int:pk>/management/solution-analytics/assignments/<int:assignment_id>/",
        SolutionManagerAssignmentView.as_view(),
    ),
    path(
        "<int:pk>/management/solution-analytics/solutions/",
        SolutionManagerSolutionsView.as_view(),
    ),
    path(
        "<int:pk>/management/solution-analytics/export/",
        SolutionManagerExportView.as_view(),
    ),
    path(
        "<int:pk>/management/solution-cases/",
        SolutionCaseAnalyticsView.as_view(),
        name="solution-case-analytics",
    ),
    path(
        "<int:pk>/management/solution-evaluation/allocation/",
        SolutionAllocationView.as_view(),
    ),
    path(
        "<int:pk>/management/solution-evaluation/allocation/apply/",
        SolutionAllocationApplyView.as_view(),
    ),
    path("<int:pk>/management/solution-evaluation/quota/", SolutionQuotaView.as_view()),
    path("<int:pk>/management/solution-results/", SolutionResultsView.as_view()),
    path(
        "<int:pk>/management/solution-results/export/",
        SolutionResultsExportView.as_view(),
    ),
    path("<int:pk>/solution-evaluation/", SolutionRatingsView.as_view()),
    path(
        "<int:pk>/solutions/<int:solution_id>/evaluation/", SolutionRatingView.as_view()
    ),
    path(
        "<int:pk>/management/solution-evaluation/experts/<int:expert_id>/assignments/",
        SolutionExpertAssignmentsView.as_view(),
    ),
    path("<int:pk>/solution-form/", SolutionFormView.as_view()),
    path("<int:pk>/management/solution-form/", ManagedSolutionFormView.as_view()),
    path("<int:pk>/solution-context/", SolutionContextView.as_view()),
    path("<int:pk>/solutions/", SolutionListCreateView.as_view()),
    path("<int:pk>/solutions/<int:solution_id>/", SolutionDetailView.as_view()),
    path("<int:pk>/solutions/<int:solution_id>/submit/", SolutionSubmitView.as_view()),
    path(
        "<int:pk>/solutions/<int:solution_id>/members/<int:user_id>/",
        SolutionMemberView.as_view(),
    ),
    path("<int:pk>/solutions/<int:solution_id>/leave/", SolutionLeaveView.as_view()),
    path("<int:pk>/solutions/<int:solution_id>/captain/", SolutionCaptainView.as_view()),
    path(
        "<int:pk>/solutions/<int:solution_id>/invitations/",
        SolutionInvitationsView.as_view(),
    ),
    path("<int:pk>/management/certificates/", CertificateSettingsView.as_view()),
    path("<int:pk>/management/certificates/assets/", CertificateAssetView.as_view()),
    path(
        "<int:pk>/management/certificates/assets/<int:asset_id>/",
        CertificateAssetView.as_view(),
    ),
    path("<int:pk>/management/certificates/preview/", CertificatePreviewView.as_view()),
    path("<int:pk>/management/certificates/test/", CertificateTestView.as_view()),
    path("<int:pk>/management/certificates/activate/", CertificateActivateView.as_view()),
    path(
        "<int:pk>/management/certificates/queue/<str:action>/",
        CertificateQueueView.as_view(),
    ),
    path(
        "<int:pk>/management/certificates/deliveries/", CertificateJournalView.as_view()
    ),
    path("<int:pk>/management/certificates/retry/", CertificateRetryView.as_view()),
    path(
        "<int:pk>/management/certificates/selection/", CertificateSelectionView.as_view()
    ),
    path(
        "<int:pk>/management/certificates/deliveries/<uuid:certificate_id>/pdf/",
        CertificateDownloadView.as_view(),
    ),
    path("<int:pk>/management/certificates/archive/", CertificateArchiveView.as_view()),
    path("<int:pk>/certificates/me/", MyCertificatesView.as_view()),
    path(
        "<int:pk>/certificates/download/<uuid:token>/",
        PublicCertificateDownloadView.as_view(),
    ),
    path(
        "<int:pk>/management/solutions/<int:solution_id>/case/preview/",
        SolutionCaseChangeView.as_view(),
    ),
    path(
        "<int:pk>/management/solutions/<int:solution_id>/members/remove/preview/",
        SolutionMemberRemovalView.as_view(),
    ),
    path(
        "<int:pk>/management/solutions/<int:solution_id>/members/remove/apply/",
        SolutionMemberRemovalView.as_view(apply_action=True),
    ),
    path(
        "<int:pk>/management/solutions/<int:solution_id>/history/",
        SolutionHistoryView.as_view(),
    ),
    path(
        "<int:pk>/management/solutions/<int:solution_id>/history/<int:change_id>/",
        SolutionHistoryView.as_view(),
    ),
    path(
        "<int:pk>/management/solutions/<int:solution_id>/case/apply/",
        SolutionCaseChangeView.as_view(apply_action=True),
    ),
    path(
        "<int:pk>/management/solutions/actions/preview/",
        SolutionActionView.as_view(),
    ),
    path(
        "<int:pk>/management/registrations/remove/preview/",
        SolutionRegistrationRemovalView.as_view(),
    ),
    path(
        "<int:pk>/management/registrations/remove/apply/",
        SolutionRegistrationRemovalView.as_view(apply_action=True),
    ),
    path(
        "<int:pk>/management/registrations/removals/",
        SolutionRegistrationRemovalHistoryView.as_view(),
    ),
    path(
        "<int:pk>/management/registrations/removals/<int:audit_id>/",
        SolutionRegistrationRemovalHistoryView.as_view(),
    ),
    path("<int:pk>/management/solutions/archive/preview/", SolutionArchiveView.as_view()),
    path(
        "<int:pk>/management/solutions/archive/apply/",
        SolutionArchiveView.as_view(apply_action=True),
    ),
    path(
        "<int:pk>/management/solutions/actions/apply/",
        SolutionActionView.as_view(apply_action=True),
    ),
    path(
        "<int:pk>/management/projects/actions/preview/",
        ManagementProjectActionPreviewView.as_view(),
    ),
    path(
        "<int:pk>/management/projects/actions/apply/",
        ManagementProjectActionApplyView.as_view(),
    ),
    path("<int:pk>/manager-overview/export/", ProgramReportView.as_view()),
    path(
        "<int:pk>/manager-overview/attention/<str:category>/<str:action>/",
        AttentionActionView.as_view(),
    ),
    path("<int:pk>/management/registration/", RegistrationSettingsView.as_view()),
    path("<int:pk>/management/registration/publish/", RegistrationPublishView.as_view()),
    path("<int:pk>/management/registration/import/", RegistrationImportView.as_view()),
    path(
        "<int:pk>/management/registration/connection/",
        RegistrationConnectionView.as_view(),
    ),
    path("<int:pk>/registration/", PublicRegistrationView.as_view()),
    path("<int:pk>/registration/<str:action>/", PublicRegistrationActionView.as_view()),
    path("organizer-invitations/<str:token>/", PublicOrganizerInvitationView.as_view()),
    path(
        "organizer-invitations/<str:token>/<str:action>/",
        PublicOrganizerInvitationActionView.as_view(),
    ),
    path("<int:pk>/management/organizers/", OrganizersView.as_view()),
    path(
        "<int:pk>/management/organizers/<int:user_id>/remove/",
        OrganizerAccessView.as_view(),
    ),
    path(
        "<int:pk>/management/organizer-invitations/<int:invitation_id>/<str:action>/",
        OrganizerInvitationActionView.as_view(),
    ),
    path(
        "<int:pk>/management/results/",
        ManagementResultsView.as_view(),
        name="management-results",
    ),
    path(
        "<int:pk>/management/results/export/",
        ManagementResultsExportView.as_view(),
        name="management-results-export",
    ),
    path("<int:pk>/management/experts/", ExpertsView.as_view()),
    path("<int:pk>/management/experts/bulk/", ExpertsBulkView.as_view()),
    path(
        "<int:pk>/management/experts/<int:expert_id>/cases/",
        ExpertCaseScopeView.as_view(),
    ),
    path("<int:pk>/management/project-experts/", ProjectExpertsView.as_view()),
    path(
        "<int:pk>/management/expert-invitations/<int:invitation_id>/<str:action>/",
        InvitationActionView.as_view(),
    ),
    path(
        "<int:pk>/management/experts/<int:expert_id>/assignments/",
        ExpertAssignmentsView.as_view(),
    ),
    path("<int:pk>/management/expert-allocation/", AllocationView.as_view()),
    path("<int:pk>/management/expert-allocation/apply/", AllocationApplyView.as_view()),
    path("<int:pk>/management/evaluators/", EvaluatorsView.as_view()),
    path(
        "<int:pk>/management/criteria/",
        ManagementCriteriaView.as_view(),
        name="management-criteria",
    ),
    path(
        "<int:pk>/management/project-form/",
        ManagementProjectFormView.as_view(),
        name="management-project-form",
    ),
    path("<int:pk>/management/", ManagementView.as_view(), name="management"),
    path(
        "<int:pk>/management/participants/selection/",
        ManagementSelectionView.as_view(),
        {"kind": "participants"},
    ),
    path(
        "<int:pk>/management/participants/remove-preview/",
        ManagementParticipantsRemovalPreviewView.as_view(),
    ),
    path(
        "<int:pk>/management/participants/remove/",
        ManagementParticipantsRemovalView.as_view(),
    ),
    path(
        "<int:pk>/management/projects/selection/",
        ManagementSelectionView.as_view(),
        {"kind": "projects"},
    ),
    path(
        "<int:pk>/management/participants/export/",
        ManagementParticipantsExportView.as_view(),
        name="management-participants-export",
    ),
    path(
        "<int:pk>/management/participants/",
        ManagementParticipantsView.as_view(),
        name="management-participants",
    ),
    path(
        "<int:pk>/management/projects/",
        ManagementProjectsView.as_view(),
        name="management-projects",
    ),
    path(
        "<int:pk>/management/projects/export/",
        ManagementProjectsExportView.as_view(),
        name="management-projects-export",
    ),
    path(
        "<int:pk>/management/projects/<int:link_id>/team/",
        ManagementTeamView.as_view(),
        name="management-team",
    ),
    path(
        "<int:pk>/management/projects/<int:link_id>/evaluation/",
        ManagementEvaluationView.as_view(),
        name="management-evaluation",
    ),
    path(
        "<int:pk>/management/settings/<str:section>/",
        ManagementSettingsView.as_view(),
        name="management-settings",
    ),
    path(
        "<int:pk>/management/materials/",
        ManagementMaterialsView.as_view(),
        name="management-materials",
    ),
    path(
        "<int:pk>/management/materials/<int:material_id>/",
        ManagementMaterialDetailView.as_view(),
        name="management-material",
    ),
    path(
        "<int:pk>/analytics-widget/",
        ProgramRoleWidgetAPIView.as_view(),
        name="analytics-widget",
    ),
    path("", PartnerProgramList.as_view()),
    path("<int:pk>/", PartnerProgramDetail.as_view()),
    path(
        "<int:pk>/manager-overview/",
        ProgramManagerAnalyticsAPIView.as_view(),
        name="manager-overview",
    ),
    path(
        "<int:pk>/manager-overview/participants-without-visit/",
        ProgramManagerParticipantsWithoutVisitAPIView.as_view(),
        name="manager-overview-participants-without-visit",
    ),
    path(
        "<int:pk>/manager-overview/participants-without-onboarding/",
        ProgramManagerParticipantsWithoutOnboardingAPIView.as_view(),
        name="manager-overview-participants-without-onboarding",
    ),
    path(
        "<int:pk>/manager-overview/participants-without-team/",
        ProgramManagerParticipantsWithoutTeamAPIView.as_view(),
        name="manager-overview-participants-without-team",
    ),
    path(
        "<int:pk>/manager-overview/projects-awaiting-evaluation/",
        ProgramManagerProjectsAwaitingEvaluationAPIView.as_view(),
        name="manager-overview-projects-awaiting-evaluation",
    ),
    path(
        "<int:pk>/manager-overview/projects-not-submitted/",
        ProgramManagerProjectsNotSubmittedAPIView.as_view(),
        name="manager-overview-projects-not-submitted",
    ),
    path(
        "<int:pk>/manager-overview/assignments/",
        ProgramManagerAssignmentsAPIView.as_view(),
        name="manager-overview-assignments",
    ),
    path(
        "<int:pk>/manager-overview/assignments/<int:assignment_id>/scores/",
        ProgramManagerAssignmentScoresAPIView.as_view(),
        name="manager-overview-assignment-scores",
    ),
    path(
        "<int:pk>/acknowledge-welcome/",
        PartnerProgramWelcomeAcknowledgement.as_view(),
        name="partner-program-acknowledge-welcome",
    ),
    path(
        "partner-program-projects/<int:pk>/submit/",
        PartnerProgramProjectSubmitView.as_view(),
        name="partner-program-project-submit",
    ),
    path(
        "partner-program-projects/<int:pk>/fields/",
        PartnerProgramProjectFieldsView.as_view(),
        name="partner-program-project-fields",
    ),
    path("<int:pk>/schema/", PartnerProgramDataSchema.as_view()),
    path("<int:pk>/register/", PartnerProgramRegister.as_view()),
    path("<int:pk>/register_new/", PartnerProgramCreateUserAndRegister.as_view()),
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
