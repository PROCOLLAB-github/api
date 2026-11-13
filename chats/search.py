from django import forms
from django.db.models import Case, Exists, F, OuterRef, Q, TextField, Value, When
from django.db.models.functions import Concat

from chats.attachments import ATTACHMENT_FIELDS, chat_attachment_field
from core.search import unicode_literal_pattern
from files.models import UserFile


class ChatMessageSearchForm(forms.Form):
    scope = forms.ChoiceField(
        label="Где искать",
        required=False,
        choices=[
            ("all", "Сообщения и вложения"),
            ("messages", "Только сообщения"),
            ("files", "Только вложения"),
        ],
        error_messages={"invalid_choice": "Выберите, где искать."},
    )
    author_id = forms.IntegerField(
        label="ID автора",
        required=False,
        min_value=1,
        max_value=2**63 - 1,
        error_messages={
            "invalid": "Укажите целое число.",
            "min_value": "ID автора должен быть положительным числом.",
            "max_value": "ID автора превышает допустимое значение.",
        },
    )

    def __init__(self, data):
        super().__init__(data)
        self.fields["q"] = forms.CharField(
            label="Поисковый запрос",
            required=False,
            max_length=200,
            error_messages={
                "max_length": "Введите не более 200 символов.",
                "null_characters_not_allowed": "В запросе есть недопустимый символ.",
            },
        )
        self.order_fields(["q", "scope", "author_id"])


def search_chat_messages(chat, filters):
    query = filters["q"]
    scope = filters["scope"]
    author_id = filters["author_id"]
    messages = chat.visible_messages()
    if author_id is not None:
        messages = messages.filter(author_id=author_id)
    if not query:
        if scope == "files":
            return messages.filter(Exists(_message_files(chat)))
        return messages
    pattern = unicode_literal_pattern(query)
    if scope == "messages":
        return messages.filter(text__regex=pattern)

    files = _message_files(chat).alias(
        filename=Case(
            When(extension="", then=F("name")),
            default=Concat("name", Value("."), "extension", output_field=TextField()),
        )
    )
    matches_file = Exists(files.filter(filename__regex=pattern))
    if scope == "files":
        return messages.filter(matches_file)
    return messages.filter(Q(text__regex=pattern) | matches_file)


def _message_files(chat):
    message_field = chat_attachment_field(chat)
    filters = {
        "file_to_message__" + field + "__isnull": True
        for field in ATTACHMENT_FIELDS.values()
        if field != message_field
    }
    filters["file_to_message__" + message_field + "_id"] = OuterRef("pk")
    return UserFile.objects.filter(**filters)
