from dataclasses import dataclass

from django import forms
from django.db.models import Q
from django.http import Http404

DEFAULT_CONTEXT_LIMIT = 20
MAX_CONTEXT_LIMIT = 50


class MessageContextForm(forms.Form):
    direction = forms.ChoiceField(
        required=False,
        choices=[
            ("around", "Вокруг сообщения"),
            ("older", "Более ранние"),
            ("newer", "Более новые"),
        ],
        error_messages={"invalid_choice": "Выберите направление загрузки сообщений."},
    )
    limit = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_CONTEXT_LIMIT,
        error_messages={
            "invalid": "Укажите целое число сообщений.",
            "min_value": "Укажите хотя бы одно сообщение.",
            "max_value": "Можно загрузить не более %(limit_value)s сообщений с каждой стороны.",
        },
    )

    def clean_direction(self):
        return self.cleaned_data["direction"] or "around"

    def clean_limit(self):
        return self.cleaned_data["limit"] or DEFAULT_CONTEXT_LIMIT


@dataclass
class MessageContext:
    messages: list
    older_than: int | None = None
    newer_than: int | None = None


def before(message):
    return Q(created_at__lt=message.created_at) | Q(
        created_at=message.created_at, pk__lt=message.pk
    )


def after(message):
    return Q(created_at__gt=message.created_at) | Q(
        created_at=message.created_at, pk__gt=message.pk
    )


def get_message_context(chat, queryset, message_id, *, direction, limit):
    """Return a chronological slice of one chat using (created_at, id) boundaries."""
    anchor = (
        chat.messages.only("id", "created_at", "is_deleted").filter(pk=message_id).first()
    )
    if anchor is None or (direction == "around" and anchor.is_deleted):
        raise Http404("Сообщение недоступно.")

    visible = chat.messages.filter(is_deleted=False)
    ids = []
    if direction in ("around", "older"):
        ids.extend(
            visible.filter(before(anchor))
            .order_by("-created_at", "-pk")
            .values_list("pk", flat=True)[:limit]
        )
    if direction == "around":
        ids.append(anchor.pk)
    if direction in ("around", "newer"):
        ids.extend(
            visible.filter(after(anchor))
            .order_by("created_at", "pk")
            .values_list("pk", flat=True)[:limit]
        )

    messages = list(
        queryset.filter(chat=chat, pk__in=ids, is_deleted=False).order_by(
            "created_at", "pk"
        )
    )
    if direction == "around" and not any(message.pk == anchor.pk for message in messages):
        raise Http404("Сообщение недоступно.")
    if not messages:
        return MessageContext(messages)

    first, last = messages[0], messages[-1]
    has_older = visible.filter(before(first)).exists()
    has_newer = visible.filter(after(last)).exists()
    return MessageContext(
        messages, first.pk if has_older else None, last.pk if has_newer else None
    )
