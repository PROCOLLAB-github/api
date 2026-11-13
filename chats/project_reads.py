from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Subquery, Value
from django.db.models.functions import Coalesce

from chats.exceptions import MessageValidationException
from chats.models import ProjectChatMessage, ProjectChatMessageRead
from chats.permissions import is_project_member
from chats.websockets_settings import ChatType, EventGroupType, EventType


def unread_project_messages(user_id):
    receipts = ProjectChatMessageRead.objects.filter(
        message_id=OuterRef("pk"), user_id=user_id
    )
    # The old shared flag cannot identify readers. Preserve it as a legacy baseline.
    return (
        ProjectChatMessage.objects.filter(is_deleted=False, is_read=False)
        .exclude(author_id=user_id)
        .filter(~Exists(receipts))
    )


def with_project_chat_unreads(queryset, user_id):
    unread = unread_project_messages(user_id).filter(chat_id=OuterRef("pk"))
    totals = unread.order_by().values("chat_id").annotate(total=Count("pk"))
    return queryset.annotate(
        unread_count=Coalesce(Subquery(totals.values("total")), Value(0)),
        first_unread_message_id=Subquery(
            unread.order_by("created_at", "pk").values("pk")[:1]
        ),
    )


def with_project_message_reads(queryset, user_id, *, include_reply=False):
    receipts = ProjectChatMessageRead.objects.filter(message_id=OuterRef("pk"))
    totals = receipts.order_by().values("message_id").annotate(total=Count("pk"))
    queryset = queryset.annotate(
        read_count=Coalesce(Subquery(totals.values("total")), Value(0)),
        read_by_me=Exists(receipts.filter(user_id=user_id)),
    )
    if include_reply:
        replies = with_project_message_reads(
            ProjectChatMessage.objects.select_related("author"), user_id
        )
        queryset = queryset.prefetch_related(Prefetch("reply_to", queryset=replies))
    return queryset


def project_message_is_read(*, legacy_read, is_author, read_by_me, read_count) -> bool:
    return legacy_read or (read_count > 0 if is_author else read_by_me)


def personalize_project_message_event(message, user_id):
    # New and edited messages are broadcast with a shared payload. Project the
    # personal flags at the socket so an edit cannot reset somebody's read state.
    message = dict(message)
    message_parts = [message]
    if message.get("reply_to") is not None:
        message["reply_to"] = dict(message["reply_to"])
        message_parts.append(message["reply_to"])
    states = with_project_message_reads(
        ProjectChatMessage.objects.filter(pk__in=[part["id"] for part in message_parts]),
        user_id,
    ).values("id", "author_id", "is_read", "read_by_me", "read_count")
    states_by_id = {state["id"]: state for state in states}
    for part in message_parts:
        state = states_by_id.get(part["id"])
        if state is None:
            continue
        part["read_count"] = state["read_count"]
        part["is_read"] = project_message_is_read(
            legacy_read=state["is_read"],
            is_author=state["author_id"] == user_id,
            read_by_me=state["read_by_me"],
            read_count=state["read_count"],
        )
    return message


@transaction.atomic
def mark_project_message_read(*, chat_id, message_id, user):
    if type(message_id) not in (int, str):
        raise MessageValidationException("Некорректный идентификатор сообщения.")
    try:
        message = (
            ProjectChatMessage.objects.select_related("chat__project")
            .select_for_update(of=("self",))
            .get(pk=message_id, chat_id=chat_id, is_deleted=False)
        )
    except (ProjectChatMessage.DoesNotExist, TypeError, ValueError) as error:
        raise MessageValidationException("Сообщение недоступно для прочтения.") from error

    if not is_project_member(user, message.chat.project):
        raise MessageValidationException("У вас нет доступа к чату проекта.")

    if message.author_id == user.pk:
        return message.author_id, 0, False
    _, created = ProjectChatMessageRead.objects.get_or_create(message=message, user=user)
    return message.author_id, message.read_receipts.count(), created


async def publish_project_message_read(
    *, chat_id, message_id, user_id, author_id, read_count, sender_channel=None
):
    event = {
        "type": EventType.READ_MESSAGE,
        "content": {
            "chat_id": chat_id,
            "chat_type": ChatType.PROJECT,
            "user_id": user_id,
            "message_id": message_id,
            "read_count": read_count,
        },
        "_project_chat_id": chat_id,
        "_project_read_audience": [user_id, author_id],
    }
    layer = get_channel_layer()
    if sender_channel is None:
        await layer.group_send(f"{EventGroupType.CHATS_RELATED}_{int(chat_id)}", event)
    else:
        await layer.send(sender_channel, event)
