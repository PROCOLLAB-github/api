from django.urls import path

from kanban.consumers import KanbanConsumer

websocket_urlpatterns = [
    path("ws/kanban/", KanbanConsumer.as_asgi()),
]
