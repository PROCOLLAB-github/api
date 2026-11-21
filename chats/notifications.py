from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from chats.attachments import get_accessible_chat
from chats.exceptions import MessageValidationException
from chats.models import ChatNotificationPreference, ProjectChat

MAX_MENTIONS = 20
Mode = ChatNotificationPreference.Mode


def _chat_field(chat_model):
    return "project_chat_id" if chat_model is ProjectChat else "program_channel_id"


def notification_settings(user, chat_model, chat_id):
    preference = ChatNotificationPreference.objects.filter(
        user=user, **{_chat_field(chat_model): chat_id}
    ).first()
    if preference is None or (
        preference.muted_until is not None and preference.muted_until <= timezone.now()
    ):
        return {"mode": Mode.ALL, "muted_until": None}
    return {"mode": preference.mode, "muted_until": preference.muted_until}


def set_notification_mode(user, chat_model, chat_id, mode):
    chat = get_accessible_chat(user, chat_model, chat_id)
    if mode not in Mode.values:
        raise MessageValidationException("Выберите режим уведомлений.")
    muted_until = timezone.now() + timedelta(hours=8) if mode == Mode.MUTE_8H else None
    ChatNotificationPreference.objects.update_or_create(
        user=user,
        **{_chat_field(chat_model): chat.pk},
        defaults={"mode": mode, "muted_until": muted_until},
    )
    return {"mode": mode, "muted_until": muted_until}


def chat_mention_recipients(chat):
    users = get_user_model().objects
    if isinstance(chat, ProjectChat):
        return users.filter(
            Q(pk=chat.project.leader_id) | Q(collaborations__project_id=chat.project_id)
        ).distinct()
    return users.filter(
        Q(pk__in=chat.program.managers.values("pk"))
        | Q(partner_program_profiles__partner_program_id=chat.program_id)
    ).distinct()


def validate_mentions(chat, author, mentioned_user_ids):
    if not isinstance(mentioned_user_ids, list) or len(mentioned_user_ids) > MAX_MENTIONS:
        raise MessageValidationException("Можно упомянуть до 20 участников.")
    if any(type(pk) is not int or not 0 < pk < 2**63 for pk in mentioned_user_ids):
        raise MessageValidationException("Некорректный список упоминаний.")
    ids = set(mentioned_user_ids)
    ids.discard(author.pk)
    if ids and chat_mention_recipients(chat).filter(pk__in=ids).count() != len(ids):
        raise MessageValidationException("Упоминать можно только участников этого чата.")
    return sorted(ids)


def should_notify(user, chat_model, chat_id, *, author_id, mentioned_user_ids):
    if user.pk == author_id:
        return False
    mode = notification_settings(user, chat_model, chat_id)["mode"]
    return mode == Mode.ALL or (mode == Mode.MENTIONS and user.pk in mentioned_user_ids)
