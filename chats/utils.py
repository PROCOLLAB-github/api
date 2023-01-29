from typing import Union, Type

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from chats.exceptions import NonMatchingReplyChatIdException
from chats.models import DirectChatMessage, ProjectChatMessage

User = get_user_model()


def clean_message_text(text: str) -> str:
    """
    Cleans message text.
    """

    return text.strip()


def validate_message_text(text: str) -> bool:
    """
    Validates message text.
    """
    # TODO: add bad word filter
    return 0 < len(text) <= 8192


def get_user_channel_cache_key(user: User) -> str:
    return f"user_channel_{user.pk}"


async def create_message(
    chat_id: Union[str, int],
    chat_model: Union[Type[DirectChatMessage], Type[ProjectChatMessage]],
    author: User,
    text: str,
    reply_to: int = None,
) -> Union[DirectChatMessage, ProjectChatMessage]:
    """
    Creates message.

    Args:
        chat_id: An integer representing chat id.
        chat_model: A chat model.
        author: A user instance.
        text: A string representing message text.
        reply_to: An integer representing message id to reply to.

    Returns:
        A message instance.

    Raises:
        NonMatchingReplyChatIdException: If reply_to message is not in chat.
    """

    try:
        return await sync_to_async(chat_model.objects.create)(
            chat_id=chat_id,
            author=author,
            text=text,
            reply_to=reply_to,
        )
    except ValidationError:
        raise NonMatchingReplyChatIdException(
            f"Message {reply_to} is not in chat {chat_id}"
        )
