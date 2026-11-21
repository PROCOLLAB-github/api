from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import Http404

from chats.exceptions import MessageValidationException
from chats.models import DirectChatBlock, DirectChatPrivacy, DirectChatSpamReport
from projects.models import Project


@dataclass(frozen=True)
class DirectContact:
    blocked_by_me: bool
    can_send: bool


def lock_contact_users(*users):
    # A first send and a privacy change must be ordered even before a chat exists.
    ids = {user.pk for user in users}
    locked = list(
        get_user_model()
        .objects.filter(pk__in=ids)
        .order_by("pk")
        .select_for_update(no_key=True)
        .values_list("pk", flat=True)
    )
    if set(locked) != ids:
        raise MessageValidationException("Пользователь недоступен.")


def get_incoming_policy(user):
    return (
        DirectChatPrivacy.objects.filter(user=user)
        .values_list("incoming", flat=True)
        .first()
        or DirectChatPrivacy.Incoming.EVERYONE
    )


@transaction.atomic
def set_incoming_policy(user, incoming):
    if incoming not in DirectChatPrivacy.Incoming.values:
        raise MessageValidationException("Выберите, кто может начать диалог.")
    lock_contact_users(user)
    DirectChatPrivacy.objects.update_or_create(user=user, defaults={"incoming": incoming})
    return incoming


@transaction.atomic
def set_block(user, other_user, blocked):
    if user.pk == other_user.pk:
        raise MessageValidationException("Нельзя заблокировать самого себя.")
    lock_contact_users(user, other_user)
    blocks = DirectChatBlock.objects.filter(user=user, blocked_user=other_user)
    if blocked:
        blocks.get_or_create(user=user, blocked_user=other_user)
    else:
        blocks.delete()


def direct_contact(user, other_user, chat=None):
    if user.pk == other_user.pk:
        return DirectContact(blocked_by_me=False, can_send=True)
    blockers = set(
        DirectChatBlock.objects.filter(
            Q(user=user, blocked_user=other_user) | Q(user=other_user, blocked_user=user)
        ).values_list("user_id", flat=True)
    )
    if blockers:
        return DirectContact(blocked_by_me=user.pk in blockers, can_send=False)
    if chat is not None and chat.messages.exists():
        return DirectContact(blocked_by_me=False, can_send=True)
    if get_incoming_policy(other_user) == DirectChatPrivacy.Incoming.EVERYONE:
        return DirectContact(blocked_by_me=False, can_send=True)

    teams = Project.objects.filter(Q(leader=user) | Q(collaborator__user=user)).values(
        "pk"
    )
    shared_team = (
        Project.objects.filter(pk__in=teams)
        .filter(Q(leader=other_user) | Q(collaborator__user=other_user))
        .exists()
    )
    return DirectContact(blocked_by_me=False, can_send=shared_team)


def require_direct_contact(user, other_user, chat):
    if not direct_contact(user, other_user, chat).can_send:
        raise MessageValidationException("Отправка сообщений в этот диалог недоступна.")


def direct_chat_opponent(chat, user):
    other = chat.users.exclude(pk=user.pk).first()
    if other is None:
        raise MessageValidationException(
            "Действие доступно в диалоге с другим пользователем."
        )
    return other


@transaction.atomic
def report_direct_spam(chat, reporter, message_id=None):
    if not chat.users.filter(pk=reporter.pk).exists():
        raise Http404("Чат недоступен.")
    other = direct_chat_opponent(chat, reporter)
    if (
        message_id is not None
        and DirectChatSpamReport.objects.filter(
            chat=chat, reporter=reporter, message_id=message_id
        ).exists()
    ):
        return
    messages = chat.visible_messages().filter(author=other)
    message = (
        messages.filter(pk=message_id).first()
        if message_id is not None
        else messages.first()
    )
    if message is None:
        raise MessageValidationException("Нет доступного входящего сообщения для жалобы.")
    DirectChatSpamReport.objects.get_or_create(
        reporter=reporter,
        message_id=message.pk,
        defaults={
            "chat": chat,
            "reported_user": other,
            "message_text": message.text,
        },
    )
