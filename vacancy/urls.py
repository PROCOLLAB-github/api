from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from vacancy.views import (
    VacancyList,
    VacancyDetail,
    VacancyRequestList,
    VacancyRequestDetail,
)

app_name = "vacancy"

urlpatterns = [
    path("", VacancyList.as_view()),
    path("<int:pk>/", VacancyDetail.as_view()),
    path("<int:pk>/requests/", VacancyRequestList.as_view()),
    path("requests/<int:pk>/", VacancyRequestDetail.as_view()),
]

urlpatterns = format_suffix_patterns(urlpatterns)
