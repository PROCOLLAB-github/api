from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from chats.attachments import get_accessible_chat
from chats.direct_privacy import (
    direct_chat_opponent,
    direct_contact,
    get_incoming_policy,
    report_direct_spam,
    set_block,
    set_incoming_policy,
)
from chats.exceptions import MessageValidationException
from chats.models import DirectChat, DirectChatPrivacy


class DirectPrivacyInput(serializers.Serializer):
    incoming = serializers.ChoiceField(
        choices=DirectChatPrivacy.Incoming.choices,
        error_messages={
            "invalid_choice": "Выберите, кто может начать диалог.",
            "required": "Выберите, кто может начать диалог.",
        },
    )


class DirectBlockInput(serializers.Serializer):
    blocked = serializers.BooleanField(
        error_messages={
            "invalid": "Укажите состояние блокировки.",
            "required": "Укажите состояние блокировки.",
        }
    )


class DirectSpamInput(serializers.Serializer):
    message_id = serializers.IntegerField(
        required=False, min_value=1, max_value=2**63 - 1
    )


@method_decorator(never_cache, name="dispatch")
class DirectPrivacyView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DirectPrivacyInput

    def get(self, request):
        return Response({"incoming": get_incoming_policy(request.user)})

    def put(self, request):
        data = self.get_serializer(data=request.data)
        data.is_valid(raise_exception=True)
        incoming = set_incoming_policy(request.user, data.validated_data["incoming"])
        return Response({"incoming": incoming})


@method_decorator(never_cache, name="dispatch")
class DirectBlockView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DirectBlockInput

    def put(self, request, id):
        chat = get_accessible_chat(request.user, DirectChat, id)
        data = self.get_serializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            other = direct_chat_opponent(chat, request.user)
            set_block(request.user, other, data.validated_data["blocked"])
        except MessageValidationException as error:
            raise ValidationError({"detail": str(error)}) from error
        contact = direct_contact(request.user, other, chat)
        return Response(
            {"blocked_by_me": contact.blocked_by_me, "can_send": contact.can_send}
        )


@method_decorator(never_cache, name="dispatch")
class DirectSpamReportView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DirectSpamInput

    def post(self, request, id):
        chat = get_accessible_chat(request.user, DirectChat, id)
        data = self.get_serializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            report_direct_spam(chat, request.user, **data.validated_data)
        except MessageValidationException as error:
            raise ValidationError({"detail": str(error)}) from error
        return Response(status=status.HTTP_204_NO_CONTENT)
