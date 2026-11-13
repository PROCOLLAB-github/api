from django.http import Http404
from django.urls import reverse

from chats.models import FileToMessage, ProjectChat
from chats.permissions import accessible_chats
from files.downloads import download_stored_file


def get_accessible_chat(user, model, chat_id):
    chat = accessible_chats(user, model).filter(pk=chat_id).first()
    if chat is None:
        raise Http404("Чат недоступен.")
    return chat


def chat_attachments(chat):
    if isinstance(chat, ProjectChat):
        return FileToMessage.objects.filter(
            project_message__chat=chat,
            project_message__is_deleted=False,
            direct_message__isnull=True,
        )
    return FileToMessage.objects.filter(
        direct_message__chat=chat,
        direct_message__is_deleted=False,
        project_message__isnull=True,
    )


def attachment_download_url(attachment, message):
    kind = "project" if attachment.project_message_id is not None else "direct"
    return reverse(
        "chats:" + kind + "-chat-attachment-download",
        args=[message.chat_id, message.pk, attachment.download_id],
    )


def download_chat_attachment(request, chat, message_id, attachment_id):
    message_field = (
        "project_message_id" if isinstance(chat, ProjectChat) else "direct_message_id"
    )
    attachments = chat_attachments(chat).filter(**{message_field: message_id})
    for attachment in attachments.select_related("file"):
        if attachment.download_id == attachment_id:
            return download_stored_file(request, attachment.file)
    raise Http404("Вложение недоступно.")
