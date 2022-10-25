from django.urls import path

from industries.views import IndustryDetail, IndustryList

app_name = "industries"

urlpatterns = [
    path("", IndustryList.as_view()),
    path("<int:pk>/", IndustryDetail.as_view()),
]
