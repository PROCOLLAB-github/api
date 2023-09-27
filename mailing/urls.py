from django.urls import path

from mailing.views import some_task

app_name = "mailing"

urlpatterns = [
    path("", some_task),
]
