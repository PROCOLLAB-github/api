from django.db.models import Exists, OuterRef, Prefetch
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_yasg.utils import swagger_auto_schema
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import GenericAPIView, ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from chats.attachments import get_accessible_chat
from chats.exceptions import MessageValidationException
from chats.models import ProgramChannel, ProgramChannelMessage
from chats.notifications import MAX_MENTIONS
from chats.pagination import MessageListPagination
from chats.permissions import accessible_chats, can_publish_in_program_channel
from chats.program_channels import (
    MAX_CHANNEL_ATTACHMENTS,
    mark_channel_read,
    publish_channel_message,
    with_channel_unreads,
)
from chats.serializers import ProgramChannelMessageSerializer
from chats.services.messages import delete_message, edit_message
from chats.views import ChatMessageHistory
from partner_programs.models import PartnerProgram


class ProgramChannelSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="pk")
    name = serializers.CharField(source="program.name")
    image_address = serializers.CharField(source="program.image_address", allow_null=True)
    unread_count = serializers.IntegerField()
    first_unread_message_id = serializers.IntegerField(allow_null=True)
    can_publish = serializers.BooleanField(read_only=True)
    last_message = serializers.SerializerMethodField()

    def get_last_message(self, channel):
        if channel.latest_messages:
            return ProgramChannelMessageSerializer(
                channel.latest_messages[0], context=self.context
            ).data
        return None

    class Meta:
        model = ProgramChannel
        fields = (
            "id",
            "name",
            "image_address",
            "can_publish",
            "unread_count",
            "first_unread_message_id",
            "last_message",
        )


class ChannelMessageInput(serializers.Serializer):
    text = serializers.CharField(
        required=False, default="", allow_blank=True, trim_whitespace=False
    )
    file_urls = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        default=list,
        max_length=MAX_CHANNEL_ATTACHMENTS,
    )
    client_message_id = serializers.UUIDField(
        required=False, allow_null=True, default=None
    )
    mentioned_user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=2**63 - 1),
        required=False,
        default=list,
        max_length=MAX_MENTIONS,
    )


class ChannelEditInput(serializers.Serializer):
    text = serializers.CharField(allow_blank=True, trim_whitespace=False)


class ChannelReadInput(serializers.Serializer):
    message_id = serializers.IntegerField(min_value=1, max_value=2**63 - 1)


class ProgramChannelSummary:
    permission_classes = [IsAuthenticated]
    serializer_class = ProgramChannelSerializer
    pagination_class = MessageListPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProgramChannel.objects.none()
        user = self.request.user
        managed = PartnerProgram.objects.filter(pk=OuterRef("pk"), managers=user)
        channels = accessible_chats(user, ProgramChannel).select_related("program")
        recent = (
            ProgramChannelMessage.objects.filter(is_deleted=False)
            .select_related("author")
            .prefetch_related("file_to_message__file")
            .order_by("-created_at", "-pk")[:1]
        )
        return (
            with_channel_unreads(channels, user.pk)
            .annotate(can_publish=Exists(managed))
            .prefetch_related(
                Prefetch("messages", queryset=recent, to_attr="latest_messages")
            )
            .order_by("program__name", "pk")
        )


@method_decorator(never_cache, name="dispatch")
class ProgramChannelList(ProgramChannelSummary, ListAPIView):
    pass


@method_decorator(never_cache, name="dispatch")
class ProgramChannelDetail(ProgramChannelSummary, RetrieveAPIView):
    lookup_url_kwarg = "id"


@method_decorator(never_cache, name="dispatch")
class ProgramChannelHistory(ChatMessageHistory):
    chat_model = ProgramChannel
    permission_classes = [IsAuthenticated]
    serializer_class = ProgramChannelMessageSerializer

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("author")
            .prefetch_related("file_to_message__file")
        )

    @swagger_auto_schema(
        request_body=ChannelMessageInput,
        responses={
            200: ProgramChannelMessageSerializer,
            201: ProgramChannelMessageSerializer,
        },
    )
    def post(self, request, id):
        require_publisher(request.user, id)
        form = ChannelMessageInput(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            publication, created = publish_channel_message(
                channel_id=id, author=request.user, **form.validated_data
            )
        except MessageValidationException as error:
            raise ValidationError({"detail": str(error)}) from error
        return Response(
            publication, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


def require_publisher(user, channel_id):
    channel = get_accessible_chat(user, ProgramChannel, channel_id)
    if not can_publish_in_program_channel(user, channel.program):
        raise PermissionDenied("Публикации доступны менеджерам программы.")
    return channel


@method_decorator(never_cache, name="dispatch")
class ProgramChannelMessageChange(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChannelEditInput

    def get_change(self, request, channel_id, message_id):
        channel = require_publisher(request.user, channel_id)
        get_object_or_404(channel.visible_messages(), pk=message_id, author=request.user)
        return dict(
            chat_model=ProgramChannel,
            chat_id=channel_id,
            message_id=message_id,
            author=request.user,
        )

    @swagger_auto_schema(
        request_body=ChannelEditInput, responses={200: ProgramChannelMessageSerializer}
    )
    def patch(self, request, id, message_id):
        change = self.get_change(request, id, message_id)
        form = self.get_serializer(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            publication = edit_message(**change, **form.validated_data)
        except MessageValidationException as error:
            raise ValidationError({"detail": str(error)}) from error
        return Response(publication)

    def delete(self, request, id, message_id):
        change = self.get_change(request, id, message_id)
        try:
            delete_message(**change)
        except MessageValidationException as error:
            raise ValidationError({"detail": str(error)}) from error
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(never_cache, name="dispatch")
class ProgramChannelReadView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChannelReadInput

    def post(self, request, id):
        get_accessible_chat(request.user, ProgramChannel, id)
        form = self.get_serializer(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            last_message_id = mark_channel_read(
                channel_id=id, user=request.user, **form.validated_data
            )
        except MessageValidationException as error:
            raise ValidationError({"detail": str(error)}) from error
        return Response({"last_message_id": last_message_id})
