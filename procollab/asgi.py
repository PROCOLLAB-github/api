import os
import chats.routing

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from chats.middleware import TokenAuthMiddleware

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": TokenAuthMiddleware(URLRouter(chats.routing.websocket_urlpatterns)),
    }
)
