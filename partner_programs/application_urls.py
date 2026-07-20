from django.urls import path

from partner_programs.applications_views import (
    ApplicationDetailView,
    ApplicationSubmitView,
    ApplicationWithdrawView,
)

app_name = "applications"

urlpatterns = [
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
