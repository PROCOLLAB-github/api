import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")

# Ensure Django app registry is loaded before importing project routes.
django_asgi_app = get_asgi_application()

from core.auth.middleware import TokenAuthMiddleware  # noqa: E402
from procollab.websocket_routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": TokenAuthMiddleware(URLRouter(websocket_urlpatterns)),
    }
)
