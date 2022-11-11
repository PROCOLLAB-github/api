from django.urls import path


from files.views import FileUploadView

app_name = "industries"

urlpatterns = [
    path("", FileUploadView.as_view()),
]
