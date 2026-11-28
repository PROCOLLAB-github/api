from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_yasg.utils import swagger_auto_schema
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from chats.drafts import (
    DRAFT_TEXT_LIMIT,
    MAX_DRAFT_REVISION,
    DraftConflict,
    draft_chat,
    draft_state,
    save_draft,
)


class ChatDraftSerializer(serializers.Serializer):
    text = serializers.CharField(
        allow_blank=True, trim_whitespace=False, max_length=DRAFT_TEXT_LIMIT
    )
    revision = serializers.IntegerField(min_value=0, max_value=MAX_DRAFT_REVISION)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)


@method_decorator(never_cache, name="dispatch")
class ChatDraftView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatDraftSerializer
    chat_model = None

    def get(self, request, id):
        chat = draft_chat(request.user, self.chat_model, id)
        return Response(self.get_serializer(draft_state(request.user, chat)).data)

    @swagger_auto_schema(responses={200: ChatDraftSerializer, 409: ChatDraftSerializer})
    def put(self, request, id):
        data = self.get_serializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            draft = save_draft(request.user, self.chat_model, id, **data.validated_data)
        except DraftConflict as error:
            return Response(
                self.get_serializer(error.current).data, status=status.HTTP_409_CONFLICT
            )
        except ValueError as error:
            raise ValidationError({"detail": str(error)}) from error
        return Response(self.get_serializer(draft).data)
