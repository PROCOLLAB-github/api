from typing import Union, Type, Optional

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from chats.exceptions import (
    NonMatchingReplyChatIdException,
    WrongChatIdException,
    NonMatchingDirectChatIdException,
)
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
    file_url: Optional[str] = None,
) -> Union[DirectChatMessage, ProjectChatMessage]:
    """
    Creates message.

    Args:
        chat_id: An integer representing chat id.
        chat_model: A chat model.
        author: A user instance.
        text: A string representing message text.
        reply_to: An integer representing message id to reply to.
        file_url: An string representing attached file url.

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
            file_url=file_url,
        )
    except ValidationError:
        raise NonMatchingReplyChatIdException(
            f"Message {reply_to} is not in chat {chat_id}"
        )


async def get_chat_and_user_ids_from_content(content, current_user) -> tuple[str, User]:
    chat_id = content["chat_id"]

    # check if chat_id is in the format of <user1_id>_<user2_id>
    try:
        user1_id, user2_id = map(int, chat_id.split("_"))
    except ValueError:
        raise WrongChatIdException(
            f'Chat id "{chat_id}" is not in the format of'
            f" <user1_id>_<user2_id>, where user1_id < user2_id"
        )

    # check if user is a member of this chat and get other user
    if user1_id == current_user.id or user2_id == current_user.id:
        other_user = await sync_to_async(User.objects.get)(
            id=user1_id if user1_id != current_user.id else user2_id
        )
    else:
        raise NonMatchingDirectChatIdException(
            f"User {current_user.id} is not a member of chat {chat_id}"
        )
    return chat_id, other_user
