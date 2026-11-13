from django.http import Http404
from django.urls import reverse

from chats.models import DirectChat, FileToMessage, ProgramChannel, ProjectChat
from chats.permissions import accessible_chats
from files.downloads import download_stored_file


def get_accessible_chat(user, model, chat_id):
    chat = accessible_chats(user, model).filter(pk=chat_id).first()
    if chat is None:
        raise Http404("Чат недоступен.")
    return chat


def chat_attachments(chat):
    message_field = chat_attachment_field(chat)
    filters = {
        field + "__isnull": True
        for field in ATTACHMENT_FIELDS.values()
        if field != message_field
    }
    filters[message_field + "__chat"] = chat
    filters[message_field + "__is_deleted"] = False
    return FileToMessage.objects.filter(**filters)


ATTACHMENT_FIELDS = {
    DirectChat: "direct_message",
    ProjectChat: "project_message",
    ProgramChannel: "channel_message",
}


def chat_attachment_field(chat):
    return ATTACHMENT_FIELDS[type(chat)]


def attachment_download_url(attachment, message):
    if attachment.channel_message_id is not None:
        kind = "program-channel"
    elif attachment.project_message_id is not None:
        kind = "project-chat"
    else:
        kind = "direct-chat"
    return reverse(
        "chats:" + kind + "-attachment-download",
        args=[message.chat_id, message.pk, attachment.download_id],
    )


def download_chat_attachment(request, chat, message_id, attachment_id):
    message_field = chat_attachment_field(chat) + "_id"
    attachments = chat_attachments(chat).filter(**{message_field: message_id})
    for attachment in attachments.select_related("file"):
        if attachment.download_id == attachment_id:
            return download_stored_file(request, attachment.file)
    raise Http404("Вложение недоступно.")
