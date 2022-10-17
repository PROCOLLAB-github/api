from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from industries.views import IndustryDetail, IndustryList

app_name = "industries"

urlpatterns = [
    path("", IndustryList.as_view()),
    path("<int:pk>/", IndustryDetail.as_view()),
]

urlpatterns = format_suffix_patterns(urlpatterns)
