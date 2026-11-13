from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from chats.attachments import get_accessible_chat
from chats.models import ProgramChannel
from chats.notifications import (
    Mode,
    chat_mention_recipients,
    notification_settings,
    set_notification_mode,
)
from chats.pagination import MessageListPagination
from chats.permissions import can_publish_in_program_channel
from users.serializers import UserChatSerializer


class NotificationModeInput(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=Mode.choices,
        error_messages={
            "invalid_choice": "Выберите режим уведомлений.",
            "required": "Выберите режим уведомлений.",
        },
    )


@method_decorator(never_cache, name="dispatch")
class ChatNotificationSettingsView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationModeInput
    chat_model = None

    def get(self, request, id):
        chat = get_accessible_chat(request.user, self.chat_model, id)
        return Response(notification_settings(request.user, self.chat_model, chat.pk))

    def put(self, request, id):
        form = self.get_serializer(data=request.data)
        form.is_valid(raise_exception=True)
        return Response(
            set_notification_mode(
                request.user, self.chat_model, id, form.validated_data["mode"]
            )
        )


@method_decorator(never_cache, name="dispatch")
class ChatMentionRecipientsView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserChatSerializer
    pagination_class = MessageListPagination
    chat_model = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        chat = get_accessible_chat(self.request.user, self.chat_model, self.kwargs["id"])
        if isinstance(chat, ProgramChannel) and not can_publish_in_program_channel(
            self.request.user, chat.program
        ):
            raise PermissionDenied("Упоминания в канале доступны менеджерам программы.")
        return (
            chat_mention_recipients(chat)
            .exclude(pk=self.request.user.pk)
            .order_by("first_name", "last_name", "pk")
        )
