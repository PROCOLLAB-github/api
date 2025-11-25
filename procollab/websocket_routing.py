from chats.routing import websocket_urlpatterns as chat_websocket_urlpatterns
from kanban.routing import websocket_urlpatterns as kanban_websocket_urlpatterns

websocket_urlpatterns = []
websocket_urlpatterns += chat_websocket_urlpatterns
websocket_urlpatterns += kanban_websocket_urlpatterns
