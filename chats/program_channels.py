from django.db import transaction
from django.db.models import BigIntegerField, Count, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from chats.channel_events import notify_channel_change
from chats.exceptions import MessageValidationException
from chats.models import ProgramChannel, ProgramChannelMessage, ProgramChannelRead
from chats.permissions import accessible_chats, can_publish_in_program_channel
from chats.serializers import ProgramChannelMessageSerializer
from chats.services.messages import _create_message
from files.downloads import is_storage_url

MAX_CHANNEL_ATTACHMENTS = 20


def channel_unread_messages(user_id):
    read = ProgramChannelRead.objects.filter(
        channel_id=OuterRef("chat_id"), user_id=user_id
    ).values("last_message_id")
    return (
        ProgramChannelMessage.objects.filter(
            is_deleted=False,
            pk__gt=Coalesce(Subquery(read), Value(0), output_field=BigIntegerField()),
        )
        .exclude(author_id=user_id)
        .order_by()
    )


def with_channel_unreads(channels, user_id):
    unread = channel_unread_messages(user_id).filter(chat_id=OuterRef("pk"))
    totals = unread.values("chat_id").annotate(total=Count("pk")).values("total")
    return channels.annotate(
        unread_count=Coalesce(Subquery(totals), Value(0)),
        first_unread_message_id=Subquery(unread.order_by("pk").values("pk")[:1]),
    )


def _locked_channel(user, channel_id):
    return (
        ProgramChannel.objects.select_related("program")
        .select_for_update(of=("self",))
        .filter(pk=channel_id, pk__in=accessible_chats(user, ProgramChannel).values("pk"))
        .first()
    )


@transaction.atomic
def publish_channel_message(*, channel_id, author, text, file_urls, client_message_id):
    channel = _locked_channel(author, channel_id)
    if channel is None or not can_publish_in_program_channel(author, channel.program):
        raise MessageValidationException("Публикации доступны менеджерам программы.")
    if len(file_urls) > MAX_CHANNEL_ATTACHMENTS:
        raise MessageValidationException("К публикации можно прикрепить до 20 файлов.")
    if not all(is_storage_url(url) for url in file_urls):
        raise MessageValidationException(
            "Один или несколько файлов недоступны для отправки."
        )
    publication, created = _create_message(
        message_model=ProgramChannelMessage,
        serializer_class=ProgramChannelMessageSerializer,
        message_link_field="channel_message",
        chat_id=channel.pk,
        author=author,
        text=text,
        reply_to_id=None,
        file_urls=file_urls,
        client_message_id=client_message_id,
    )
    if created:
        notify_channel_change(channel.pk)
    return publication, created


@transaction.atomic
def mark_channel_read(*, channel_id, user, message_id):
    channel = _locked_channel(user, channel_id)
    if channel is None or not channel.visible_messages().filter(pk=message_id).exists():
        raise MessageValidationException("Публикация недоступна.")
    receipt, created = ProgramChannelRead.objects.get_or_create(
        channel=channel, user=user, defaults={"last_message_id": message_id}
    )
    if not created and receipt.last_message_id < message_id:
        receipt.last_message_id = message_id
        receipt.save(update_fields=["last_message_id"])
    return receipt.last_message_id
