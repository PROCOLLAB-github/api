from typing import Union, Type

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from chats.exceptions import (
    NonMatchingReplyChatIdException,
    WrongChatIdException,
    NonMatchingDirectChatIdException,
)
from chats.models import DirectChatMessage, ProjectChatMessage, FileToMessage, BaseMessage
from files.models import UserFile

User = get_user_model()


def clean_message_text(text: str) -> str:
    """
    Cleans message text. -
    """

    return text.strip()


def validate_message_text(text: str) -> bool:
    """
    Validates message text. -
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


async def create_file_to_message(
    direct_message: Union[str, None, DirectChatMessage],
    project_message: Union[str, None, ProjectChatMessage],
    file: str,
) -> FileToMessage:
    return await sync_to_async(FileToMessage.objects.create)(
        direct_message=direct_message, project_message=project_message, file=file
    )


async def match_files_and_messages(
    file_urls: list[str], messages: dict[str, Union[str, None, ProjectChatMessage]]
):
    for url in file_urls:
        file = await sync_to_async(UserFile.objects.get)(pk=url)
        # implicitly matches a file and a message
        await create_file_to_message(
            direct_message=messages["direct_message"],
            project_message=messages["project_message"],
            file=file,
        )


def get_all_files(messages: list[BaseMessage]) -> list[str]:
    # looks like something bad -
    files = []
    for message in messages:
        if hasattr(message, "file_to_message"):
            files_in_message = [
                file_to_message.file for file_to_message in message.file_to_message.all()
            ]
            files.extend(files_in_message)

    return files
