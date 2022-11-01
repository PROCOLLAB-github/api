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
    path("<int:pk>/responses/", VacancyResponseList.as_view()),
    path("responses/<int:pk>/", VacancyResponseDetail.as_view()),
]
