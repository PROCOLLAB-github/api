from django.urls import path
from .views import alert_webhook

app_name = "alerts"

urlpatterns = [
    path("webhook/", alert_webhook, name="alert_webhook"),
]
