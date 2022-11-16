from django.urls import path


from metrics.views import MetricsView

app_name = "metrics"

urlpatterns = [
    path("", MetricsView.as_view()),
]
