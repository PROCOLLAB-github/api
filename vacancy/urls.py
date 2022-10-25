from django.urls import path

from vacancy.views import (
    VacancyList,
    VacancyDetail,
    VacancyResponseList,
    VacancyResponseDetail,
)

app_name = "vacancies"

urlpatterns = [
    path("", VacancyList.as_view()),
    path("<int:pk>/", VacancyDetail.as_view()),
    path("<int:pk>/requests/", VacancyResponseList.as_view()),
    path("requests/<int:pk>/", VacancyResponseDetail.as_view()),
]
