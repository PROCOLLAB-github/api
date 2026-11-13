from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from chats.websockets_settings import EventGroupType, EventType


def channel_group(channel_id):
    return f"{EventGroupType.PROGRAM_CHANNEL}_{channel_id}"


def notify_channel_change(channel_id):
    layer = get_channel_layer()
    if layer is None:
        return
    transaction.on_commit(
        lambda: async_to_sync(layer.group_send)(
            channel_group(channel_id),
            {
                "type": EventType.PROGRAM_CHANNEL_CHANGED,
                "content": {"channel_id": channel_id},
            },
        ),
        robust=True,
    )
