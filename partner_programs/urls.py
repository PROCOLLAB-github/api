# Roadmap: DEV-076, DEV-056

from django.urls import path

from news.views import NewsDetail, NewsDetailSetLiked, NewsDetailSetViewed, NewsList
from partner_programs.applications_views import (
    MyProgramApplicationView,
    ProgramApplicationCreateView,
)
from partner_programs.evaluation_views import (
    ProgramEvaluationDetailView,
    ProgramEvaluationListView,
)
from partner_programs.manager_overview_views import ManagerProgramOverviewView
from partner_programs.submission_assignment_views import (
    ProgramSubmissionAssignmentListCreateView,
)
from partner_programs.views import (
    PartnerProgramCreateUserAndRegister,
    PartnerProgramDataSchema,
    PartnerProgramDetail,
    PartnerProgramExportProjectsAPIView,
    PartnerProgramExportRatesAPIView,
    PartnerProgramList,
    PartnerProgramProjectApplyView,
    PartnerProgramProjectsAPIView,
    PartnerProgramProjectSubmitView,
    PartnerProgramRegister,
    PartnerProgramSetLiked,
    PartnerProgramSetViewed,
    ProgramFiltersAPIView,
    ProgramProjectFilterAPIView,
)

app_name = "partner_programs"

urlpatterns = [
    path("", PartnerProgramList.as_view()),
    path(
        "<int:program_id>/manager-overview/",
        ManagerProgramOverviewView.as_view(),
        name="manager-overview",
    ),
    path(
        "<int:program_id>/evaluations/",
        ProgramEvaluationListView.as_view(),
        name="evaluation-list",
    ),
    path(
        "<int:program_id>/evaluations/<int:evaluation_id>/",
        ProgramEvaluationDetailView.as_view(),
        name="evaluation-detail",
    ),
    path(
        "<int:program_id>/submission-assignments/",
        ProgramSubmissionAssignmentListCreateView.as_view(),
        name="submission-assignment-list-create",
    ),
    path(
        "<int:program_id>/applications/my/",
        MyProgramApplicationView.as_view(),
        name="my-application",
    ),
    path(
        "<int:program_id>/applications/",
        ProgramApplicationCreateView.as_view(),
        name="application-create",
    ),
    path("<int:pk>/", PartnerProgramDetail.as_view()),
    path(
        "partner-program-projects/<int:pk>/submit/",
        PartnerProgramProjectSubmitView.as_view(),
        name="partner-program-project-submit",
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
