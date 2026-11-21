from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.http import Http404

from chats.models import ChatDraft, DirectChat, ProgramChannel, ProjectChat
from chats.permissions import accessible_chats, can_publish_in_program_channel

CHAT_FIELDS = {
    DirectChat: "direct_chat_id",
    ProjectChat: "project_chat_id",
    ProgramChannel: "program_channel_id",
}
DRAFT_TEXT_LIMIT = ChatDraft._meta.get_field("text").max_length
MAX_DRAFT_REVISION = 2**53 - 1


class DraftConflict(Exception):
    def __init__(self, current):
        self.current = current


def draft_chat(user, chat_model, chat_id, *, lock=False):
    chats = chat_model.objects.filter(
        pk=chat_id, pk__in=accessible_chats(user, chat_model).values("pk")
    )
    if lock:
        chats = chats.select_for_update()
    chat = chats.first()
    if chat is None:
        raise Http404("Чат недоступен.")
    if chat_model is ProgramChannel and not can_publish_in_program_channel(
        user, chat.program
    ):
        raise PermissionDenied("Черновики канала доступны менеджерам программы.")
    return chat


def _drafts(user, chat_model, chat_id):
    return ChatDraft.objects.filter(user=user, **{CHAT_FIELDS[chat_model]: chat_id})


def with_draft_marker(chats, user):
    drafts = _drafts(user, chats.model, OuterRef("pk")).exclude(text="")
    return chats.annotate(has_draft=Exists(drafts))


def draft_state(user, chat):
    draft = (
        _drafts(user, type(chat), chat.pk)
        .values("text", "revision", "updated_at")
        .first()
    )
    return draft or {"text": "", "revision": 0, "updated_at": None}


@transaction.atomic
def save_draft(user, chat_model, chat_id, *, text, revision):
    chat = draft_chat(user, chat_model, chat_id, lock=True)
    if not isinstance(text, str) or "\x00" in text or len(text) > DRAFT_TEXT_LIMIT:
        raise ValueError("Введите текст черновика длиной до 8192 символов.")
    if type(revision) is not int or not 0 <= revision <= MAX_DRAFT_REVISION:
        raise ValueError("Некорректная версия черновика.")
    if not text.strip():
        text = ""
    current = draft_state(user, chat)
    if text == current["text"]:
        return current
    if revision != current["revision"]:
        raise DraftConflict(current)
    if revision == MAX_DRAFT_REVISION:
        raise ValueError("Невозможно сохранить следующую версию черновика.")
    # Keep the revision when clearing so delayed writes cannot restore old text.
    draft, _ = ChatDraft.objects.update_or_create(
        user=user,
        **{CHAT_FIELDS[chat_model]: chat.pk},
        defaults={"text": text, "revision": revision + 1},
    )
    return {
        "text": draft.text,
        "revision": draft.revision,
        "updated_at": draft.updated_at,
    }
