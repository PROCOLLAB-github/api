from django.conf import settings
from django.contrib.auth import get_user_model

from chats.exceptions import (
    WrongChatIdException,
    NonMatchingDirectChatIdException,
)

User = get_user_model()


async def orm_get(queryset, **kwargs):
    if settings.RUNNING_TESTS:
        return queryset.get(**kwargs)
    return await queryset.aget(**kwargs)


async def orm_exists(queryset) -> bool:
    if settings.RUNNING_TESTS:
        return queryset.exists()
    return await queryset.aexists()


async def orm_save(instance, update_fields=None):
    if settings.RUNNING_TESTS:
        instance.save(update_fields=update_fields)
        return
    await instance.asave(update_fields=update_fields)


def get_user_channel_cache_key(user: User) -> str:
    return f"user_channel_{user.pk}"


async def get_chat_and_user_ids_from_content(content, current_user) -> tuple[str, User]:
    chat_id = content["chat_id"]

    # check if chat_id is in the format of <user1_id>_<user2_id>
    try:
        user1_id, user2_id = map(int, chat_id.split("_"))
    except (AttributeError, ValueError):
        raise WrongChatIdException(
            f'Chat id "{chat_id}" is not in the format of'
            f" <user1_id>_<user2_id>, where user1_id < user2_id"
        )

    # check if user is a member of this chat and get other user
    if user1_id == current_user.id or user2_id == current_user.id:
        try:
            other_user = await orm_get(
                User.objects, id=user1_id if user1_id != current_user.id else user2_id
            )
        except User.DoesNotExist as error:
            raise WrongChatIdException("Собеседник не найден.") from error
    else:
        raise NonMatchingDirectChatIdException(
            f"User {current_user.id} is not a member of chat {chat_id}"
        )
    return chat_id, other_user
