from urllib.parse import parse_qs

import jwt
from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.authtoken.models import Token
from users.models import CustomUser
from django.contrib.auth.models import AnonymousUser


User = get_user_model()


class TokenAuthentication:
    """
    Simple token based authentication.

    Clients should authenticate by passing the token key in the query parameters.
    For example:

        ?token=401f7ac837da42b97f613d789819ff93537bee6a
    """

    model = None

    def get_model(self) -> Token:
        if self.model is not None:
            return self.model

        return Token

    """
    A custom token model may be used, but must have the following properties.

    * key -- The string identifying the token
    * user -- The user to which the token belongs
    """

    def authenticate_credentials(self, key: str) -> CustomUser:
        model = self.get_model()
        try:
            token = model.objects.select_related("user").get(key=key)
        except model.DoesNotExist:
            raise AuthenticationFailed(_("Invalid token."))

        if not token.user.is_active:
            raise AuthenticationFailed(_("User inactive or deleted."))

        return token.user

    def authenticate(self, token: Token) -> CustomUser:
        """
        Returns a `User` if a correct username and password have been supplied
        Args:
            token: token key

        Returns:
            User: A user instance.
        """
        try:
            user_id = jwt.decode(
                jwt=token, key=settings.SECRET_KEY, algorithms=["HS256"]
            )["user_id"]
        except jwt.exceptions.DecodeError:
            raise AuthenticationFailed(_("Invalid token."))
        except jwt.exceptions.ExpiredSignatureError:
            raise AuthenticationFailed(_("Token expired."))

        user = User.objects.get(pk=user_id)
        return user


@database_sync_to_async
def get_user(scope: dict) -> CustomUser | AnonymousUser:
    """
    Return the user model instance associated with the given scope.
    If no user is retrieved, return an instance of `AnonymousUser`.
    """
    # postpone model import to avoid ImproperlyConfigured error before Django
    # setup is complete.

    if "token" not in scope:
        raise ValueError(
            "Cannot find token in scope. You should wrap your consumer in "
            "TokenAuthMiddleware."
        )
    token = scope["token"]
    user = None
    try:
        auth = TokenAuthentication()
        user = auth.authenticate(token)
    except AuthenticationFailed:
        pass
    return user or AnonymousUser()


class TokenAuthMiddleware:
    """
    Custom middleware that takes a token from the query string and authenticates via Django Rest Framework authtoken.
    """

    def __init__(self, app):
        # Store the ASGI application we were passed
        self.app = app

    async def __call__(self, scope, receive, send):
        # Look up user from query string

        # TODO: (you should also do things like
        #  checking if it is a valid user ID, or if scope["user" ] is already
        #  populated).

        query_string = scope["query_string"].decode()
        query_dict = parse_qs(query_string)
        try:
            token = query_dict["token"][0]
            if token is None:
                raise ValueError("Token is missing from headers")

            scope["token"] = token
            scope["user"] = await get_user(scope)
        except (ValueError, KeyError, IndexError):
            # Token is missing from query string
            from django.contrib.auth.models import AnonymousUser

            scope["user"] = AnonymousUser()

        return await self.app(scope, receive, send)
