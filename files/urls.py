from django.urls import path

from files.views import FileView

app_name = "industries"

urlpatterns = [
    path("", FileView.as_view()),
]
