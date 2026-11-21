from channels.layers import get_channel_layer
from django.core.cache import cache
from django.db.models import Count, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from chats.exceptions import MessageValidationException
from chats.models import DirectChatMessage
from chats.utils import get_user_channel_cache_key
from chats.websockets_settings import ChatType, EventType


def unread_direct_messages(user_id):
    return DirectChatMessage.objects.filter(is_read=False, is_deleted=False).exclude(
        author_id=user_id
    )


def with_direct_chat_unreads(chats, user_id):
    unread = unread_direct_messages(user_id).filter(chat_id=OuterRef("pk"))
    totals = unread.order_by().values("chat_id").annotate(total=Count("pk"))
    return chats.annotate(
        unread_count=Coalesce(Subquery(totals.values("total")), Value(0)),
        first_unread_message_id=Subquery(
            unread.order_by("created_at", "pk").values("pk")[:1]
        ),
    )


def mark_direct_message_read(*, chat_id, message_id, user, author):
    if type(message_id) not in (str, int):
        raise MessageValidationException("Некорректный идентификатор сообщения.")
    try:
        messages = DirectChatMessage.objects.filter(
            pk=message_id,
            chat_id=chat_id,
            chat__users=user,
            author=author,
            is_deleted=False,
        ).filter(chat__users=author)
        if user.pk != author.pk and messages.update(is_read=True):
            return int(message_id)
    except (TypeError, ValueError):
        pass
    raise MessageValidationException("Сообщение недоступно для прочтения.")


async def publish_direct_message_read(
    *, chat_id, message_id, user, author, sender_channel=None
):
    layer = get_channel_layer()
    if layer is None:
        return
    channels = {
        sender_channel or cache.get(get_user_channel_cache_key(user)),
        cache.get(get_user_channel_cache_key(author)),
    }
    event = {
        "type": EventType.READ_MESSAGE,
        "content": {
            "chat_id": chat_id,
            "chat_type": ChatType.DIRECT,
            "user_id": user.pk,
            "message_id": message_id,
        },
        "_direct_chat_id": chat_id,
    }
    for channel in channels - {None}:
        await layer.send(channel, event)
