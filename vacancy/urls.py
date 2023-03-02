from django.urls import path


from vacancy.views import (
    VacancyList,
    VacancyDetail,
    VacancyResponseList,
    VacancyResponseDetail,
    VacancyResponseAccept,
    VacancyResponseDecline,
)

app_name = "vacancies"

urlpatterns = [
    path("", VacancyList.as_view()),
    path("<int:pk>/", VacancyDetail.as_view()),
    path("<int:vacancy_id>/responses/", VacancyResponseList.as_view()),
    path("responses/<int:pk>/", VacancyResponseDetail.as_view()),
    path("responses/<int:pk>/accept/", VacancyResponseAccept.as_view()),
    path("responses/<int:pk>/decline/", VacancyResponseDecline.as_view()),
]
