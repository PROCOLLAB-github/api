from django.urls import include, path
from rest_framework.routers import DefaultRouter

from kanban.views import BoardViewSet

app_name = "kanban"

router = DefaultRouter()
router.register(r"boards", BoardViewSet, basename="kanban-board")

urlpatterns = [path("", include(router.urls))]
