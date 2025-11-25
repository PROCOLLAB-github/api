from django.urls import include, path
from rest_framework.routers import DefaultRouter

from kanban.views import BoardViewSet, BoardColumnViewSet

app_name = "kanban"

router = DefaultRouter()
router.register(r"boards", BoardViewSet, basename="kanban-board")
router.register(r"columns", BoardColumnViewSet, basename="kanban-column")

urlpatterns = [path("", include(router.urls))]
