import jwt
from django.conf import settings


def clean_message_text(text: str) -> str:
    """
    Cleans message text.
    """

    return text.strip()


def validate_message_text(text: str) -> bool:
    """
    Validates message text.
    """

    return 0 < len(text) <= 8192


def get_user_id_from_token(token: str) -> int:
    """
    Returns user id from token.
    """

    return jwt.decode(jwt=token, key=settings.SECRET_KEY, algorithms=["HS256"])["user_id"]
