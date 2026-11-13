from channels.db import database_sync_to_async
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


@database_sync_to_async
def get_user(scope):
    """
    Return the user model instance associated with the given scope.
    If no user is retrieved, return an instance of `AnonymousUser`.
    """
    # postpone model import to avoid ImproperlyConfigured error before Django
    # setup is complete.
    from django.contrib.auth.models import AnonymousUser

    if "token" not in scope:
        raise ValueError(
            "Cannot find token in scope. You should wrap your consumer in "
            "TokenAuthMiddleware."
        )
    token = scope["token"]
    try:
        auth = JWTAuthentication()
        return auth.get_user(auth.get_validated_token(token))
    except AuthenticationFailed:
        return AnonymousUser()


class TokenAuthMiddleware:
    """
    Custom middleware that takes a token from WebSocket subprotocols and authenticates via JWT.
    """

    SUBPROTOCOL_KEYWORD = "Bearer"

    def __init__(self, app):
        # Store the ASGI application we were passed
        self.app = app

    async def __call__(self, scope, receive, send):
        # Extract token from Sec-WebSocket-Protocol header.
        token = self._extract_token_from_subprotocol(scope.get("subprotocols", []))

        if token:
            scope["token"] = token
            scope["user"] = await get_user(scope)
        else:
            from django.contrib.auth.models import AnonymousUser

            scope["user"] = AnonymousUser()

        return await self.app(scope, receive, send)

    def _extract_token_from_subprotocol(self, subprotocols: list[str]) -> str | None:
        """
        Expect subprotocols in the form ["Bearer", "<JWT>"].
        """
        if not subprotocols:
            return None

        if len(subprotocols) >= 2 and subprotocols[0] == self.SUBPROTOCOL_KEYWORD:
            return subprotocols[1]

        return None
