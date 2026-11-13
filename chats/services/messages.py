from uuid import UUID

from django.db import transaction

from chats.channel_events import notify_channel_change
from chats.exceptions import MessageValidationException
from chats.models import (
    DirectChat,
    DirectChatMessage,
    FileToMessage,
    ProgramChannel,
    ProgramChannelMessage,
    ProjectChat,
    ProjectChatMessage,
)
from chats.permissions import (
    accessible_chats,
    can_publish_in_program_channel,
    is_project_member,
)
from chats.serializers import (
    DirectChatMessageListSerializer,
    ProgramChannelMessageSerializer,
    ProjectChatMessageListSerializer,
)
from files.models import UserFile


def _normalize_client_message_id(value):
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise MessageValidationException(
            "Некорректный идентификатор отправляемого сообщения."
        ) from error


def _normalize_message(text, file_urls):
    if not isinstance(text, str) or "\x00" in text:
        raise MessageValidationException("Некорректный текст сообщения.")
    if file_urls is None:
        file_urls = []
    if not isinstance(file_urls, list) or any(
        not isinstance(url, str) or not url or "\x00" in url for url in file_urls
    ):
        raise MessageValidationException("Некорректный список вложений.")
    if not text.strip() and not file_urls:
        raise MessageValidationException("Сообщение не может быть пустым.")
    if len(text) > DirectChatMessage._meta.get_field("text").max_length:
        raise MessageValidationException(
            "Текст сообщения не должен превышать 8192 символа."
        )
    return list(dict.fromkeys(file_urls))


def _get_reply(message_model, chat_id, reply_to_id):
    if reply_to_id is None:
        return None
    try:
        return message_model.objects.get(
            pk=reply_to_id,
            chat_id=chat_id,
            is_deleted=False,
        )
    except (message_model.DoesNotExist, TypeError, ValueError) as error:
        raise MessageValidationException(
            "Нельзя ответить на сообщение из другого чата или удаленное сообщение."
        ) from error


def _get_files(file_urls, author):
    if not file_urls:
        return []
    files = {
        user_file.pk: user_file
        for user_file in UserFile.objects.select_for_update()
        .filter(
            pk__in=file_urls,
            user_id=author.pk,
        )
        .order_by("pk")
    }
    if len(files) != len(file_urls):
        raise MessageValidationException(
            "Один или несколько файлов недоступны для отправки."
        )
    if FileToMessage.objects.filter(file_id__in=file_urls).exists():
        raise MessageValidationException(
            "Один или несколько файлов уже прикреплены к сообщению."
        )
    return [files[url] for url in file_urls]


def _serialize_message(message_model, serializer_class, message_id):
    messages = message_model.objects.select_related("author").prefetch_related(
        "file_to_message__file"
    )
    if message_model is not ProgramChannelMessage:
        messages = messages.select_related("reply_to__author")
    message = messages.get(pk=message_id)
    return serializer_class(message).data


def _create_message(
    *,
    message_model,
    serializer_class,
    message_link_field,
    chat_id,
    author,
    text,
    reply_to_id,
    file_urls,
    client_message_id,
):
    client_message_id = _normalize_client_message_id(client_message_id)
    if client_message_id is not None:
        existing_message = message_model.objects.filter(
            chat_id=chat_id,
            author=author,
            client_message_id=client_message_id,
        ).first()
        if existing_message is not None:
            if existing_message.is_deleted:
                raise MessageValidationException("Сообщение уже удалено.")
            return (
                _serialize_message(
                    message_model,
                    serializer_class,
                    existing_message.pk,
                ),
                False,
            )

    file_urls = _normalize_message(text, file_urls)
    reply = {}
    if message_model is not ProgramChannelMessage:
        reply["reply_to"] = _get_reply(message_model, chat_id, reply_to_id)
    files = _get_files(file_urls, author)
    message = message_model.objects.create(
        chat_id=chat_id,
        author=author,
        text=text,
        client_message_id=client_message_id,
        **reply,
    )
    for user_file in files:
        FileToMessage.objects.create(file=user_file, **{message_link_field: message})
    return _serialize_message(message_model, serializer_class, message.pk), True


@transaction.atomic
def create_direct_message(
    *,
    author,
    other_user,
    text,
    reply_to_id=None,
    file_urls=None,
    client_message_id=None,
):
    chat = get_direct_chat_for_participants(author, other_user)
    # Serialize sends in this chat before checking for a repeat or locking files.
    DirectChat.objects.select_for_update().get(pk=chat.pk)
    return _create_message(
        message_model=DirectChatMessage,
        serializer_class=DirectChatMessageListSerializer,
        message_link_field="direct_message",
        chat_id=chat.pk,
        author=author,
        text=text,
        reply_to_id=reply_to_id,
        file_urls=file_urls,
        client_message_id=client_message_id,
    )


@transaction.atomic
def get_direct_chat_for_participants(user, other_user):
    chat = DirectChat.get_chat(user, other_user)
    participants = set(chat.users.values_list("pk", flat=True))
    if participants != {user.pk, other_user.pk}:
        raise MessageValidationException("Чат недоступен.")
    return chat


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


@transaction.atomic
def create_project_message(
    *,
    chat_id,
    author,
    text,
    reply_to_id=None,
    file_urls=None,
    client_message_id=None,
):
    try:
        chat = (
            ProjectChat.objects.select_related("project")
            .select_for_update(of=("self",))
            .get(pk=chat_id)
        )
    except (ProjectChat.DoesNotExist, TypeError, ValueError) as error:
        raise MessageValidationException("У вас нет доступа к чату проекта.") from error
    if not is_project_member(author, chat.project):
        raise MessageValidationException("У вас нет доступа к чату проекта.")
    return _create_message(
        message_model=ProjectChatMessage,
        serializer_class=ProjectChatMessageListSerializer,
        message_link_field="project_message",
        chat_id=chat.pk,
        author=author,
        text=text,
        reply_to_id=reply_to_id,
        file_urls=file_urls,
        client_message_id=client_message_id,
    )


def _get_message_for_change(chat_model, chat_id, message_id, author):
    if type(message_id) not in (str, int):
        raise MessageValidationException("Некорректный идентификатор сообщения.")
    chat = (
        chat_model.objects.select_for_update()
        .filter(pk=chat_id, pk__in=accessible_chats(author, chat_model).values("pk"))
        .first()
    )
    if chat is None:
        raise MessageValidationException("Чат недоступен.")
    if chat_model is ProgramChannel:
        if not can_publish_in_program_channel(author, chat.program):
            raise MessageValidationException("Публикации доступны менеджерам программы.")
    try:
        message = chat.messages.filter(pk=message_id, author=author).first()
    except (TypeError, ValueError):
        message = None
    if message is None:
        raise MessageValidationException("Сообщение недоступно для изменения.")
    return message


@transaction.atomic
def edit_message(*, chat_model, chat_id, message_id, author, text):
    message = _get_message_for_change(chat_model, chat_id, message_id, author)
    if message.is_deleted:
        raise MessageValidationException("Сообщение уже удалено.")
    if not isinstance(text, str) or "\x00" in text:
        raise MessageValidationException("Некорректный текст сообщения.")
    if len(text) > message._meta.get_field("text").max_length:
        raise MessageValidationException(
            "Текст сообщения не должен превышать 8192 символа."
        )
    if not text.strip() and not message.file_to_message.exists():
        raise MessageValidationException("Сообщение не может быть пустым.")
    if message.text != text or not message.is_edited:
        message.text = text
        message.is_edited = True
        message.save(update_fields=["text", "is_edited"])
        if chat_model is ProgramChannel:
            notify_channel_change(chat_id)
    serializer_class = {
        DirectChat: DirectChatMessageListSerializer,
        ProjectChat: ProjectChatMessageListSerializer,
        ProgramChannel: ProgramChannelMessageSerializer,
    }[chat_model]
    return _serialize_message(type(message), serializer_class, message.pk)


@transaction.atomic
def delete_message(*, chat_model, chat_id, message_id, author):
    message = _get_message_for_change(chat_model, chat_id, message_id, author)
    if not message.is_deleted:
        message.is_deleted = True
        message.save(update_fields=["is_deleted"])
        if chat_model is ProgramChannel:
            notify_channel_change(chat_id)
    return message.pk
