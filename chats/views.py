from django import forms
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from rest_framework import status
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
)
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from chats.attachments import (
    chat_attachments,
    download_chat_attachment,
    get_accessible_chat,
)
from chats.message_context import (
    MAX_CONTEXT_LIMIT,
    MessageContextForm,
    get_message_context,
)
from chats.models import ProjectChat, DirectChat
from chats.pagination import MessageListPagination
from chats.permissions import IsProjectChatMember, IsChatMember, accessible_chats
from chats.project_reads import (
    unread_project_messages,
    with_project_chat_unreads,
    with_project_message_reads,
)
from chats.search import ChatMessageSearchForm, search_chat_messages
from chats.serializers import (
    DirectChatListSerializer,
    DirectChatMessageListSerializer,
    ProjectChatListSerializer,
    ProjectChatMessageListSerializer,
    ProjectChatDetailSerializer,
    DirectChatDetailSerializer,
    ChatAttachmentSerializer,
)

User = get_user_model()


class DirectChatList(ListAPIView):
    serializer_class = DirectChatListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return DirectChat.objects.prefetch_related("users").filter(
            users=self.request.user
        )

    def get(self, request, *args, **kwargs):
        chats = self.get_queryset()
        serialized_chats = []
        for chat in chats:
            try:
                user1_id, _ = map(int, chat.id.split("_"))
                # TODO сделать проверку на удаление профиля
                if user1_id == request.user.id:
                    opponent = chat.users.all()[1]
                else:
                    opponent = chat.users.first()

                context = {"opponent": opponent}
                serialized_chat = DirectChatListSerializer(chat, context=context).data
                serialized_chats.append(serialized_chat)
            except IndexError:
                pass
        return Response(serialized_chats, status=status.HTTP_200_OK)


class ProjectChatList(ListAPIView):
    serializer_class = ProjectChatListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return ProjectChat.objects.none()
        return with_project_chat_unreads(
            user.get_project_chats().select_related("project"), user.pk
        )


class ProjectChatDetail(RetrieveAPIView):
    queryset = ProjectChat.objects.all()
    serializer_class = ProjectChatDetailSerializer
    permission_classes = [IsProjectChatMember]

    def get_queryset(self):
        return with_project_chat_unreads(
            super().get_queryset().select_related("project"), self.request.user.pk
        )


class DirectChatDetail(RetrieveAPIView):
    queryset = DirectChat.objects.all()
    serializer_class = DirectChatDetailSerializer
    permission_classes = [IsAuthenticated, IsChatMember]

    def get(self, request, *args, **kwargs) -> Response:
        try:
            assert "_" in self.kwargs["id"], "processed id must contain underscore"

            user1_id, user2_id = map(int, self.kwargs["id"].split("_"))

            assert (
                request.user.id == user1_id or request.user.id == user2_id
            ), "current user id is not present in raw id"

            user1 = User.objects.get(pk=user1_id)
            user2 = User.objects.get(pk=user2_id)

            if user1 == request.user:
                opponent = user2
            else:
                opponent = user1
            context = {"opponent": opponent}
            data = DirectChatDetailSerializer(
                DirectChat.get_chat(user1, user2), context=context
            ).data

            data["name"] = f"{opponent.first_name} {opponent.last_name}"
            data["image_address"] = opponent.avatar

            return Response(
                status=status.HTTP_200_OK,
                data=data,
            )

        except ValueError:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "detail": "processed id must contain two integers separated by underscore"
                },
            )
        except AssertionError as e:
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"detail": str(e)})
        except User.DoesNotExist:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"detail": "One or both users do not exist"},
            )
        except DirectChat.DoesNotExist:
            return Response(
                status=status.HTTP_404_NOT_FOUND,
                data={"detail": "Direct chat does not exist"},
            )


class ChatMessageHistory(ListCreateAPIView):
    pagination_class = MessageListPagination

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                "q",
                openapi.IN_QUERY,
                description="Текст сообщения или имя файла",
                type=openapi.TYPE_STRING,
                max_length=200,
            ),
            openapi.Parameter(
                "scope",
                openapi.IN_QUERY,
                description="Где искать",
                type=openapi.TYPE_STRING,
                enum=["all", "messages", "files"],
            ),
            openapi.Parameter(
                "author_id",
                openapi.IN_QUERY,
                description="ID автора сообщения",
                type=openapi.TYPE_INTEGER,
                minimum=1,
            ),
        ]
    )
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        if hasattr(self, "sync_cursor"):
            response.data["sync_cursor"] = self.sync_cursor
        return response

    def get_queryset(self):
        user = self.request.user
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        chat = get_object_or_404(
            accessible_chats(user, self.chat_model), pk=self.kwargs["id"]
        )
        form = ChatMessageSearchForm(self.request.query_params)
        if not form.is_valid():
            raise ValidationError(form.errors)
        if (
            not form.cleaned_data["q"]
            and form.cleaned_data["author_id"] is None
            and form.cleaned_data["scope"] != "files"
        ):
            self.sync_cursor = chat.message_revision
        return search_chat_messages(chat, form.cleaned_data)


class DirectChatMessageList(ChatMessageHistory):
    chat_model = DirectChat
    serializer_class = DirectChatMessageListSerializer
    permission_classes = [IsAuthenticated, IsChatMember]

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("author", "reply_to__author")
            .prefetch_related("file_to_message__file")
        )


class ProjectChatMessageList(ChatMessageHistory):
    chat_model = ProjectChat
    serializer_class = ProjectChatMessageListSerializer
    permission_classes = [IsProjectChatMember]

    def get_queryset(self):
        messages = (
            super()
            .get_queryset()
            .select_related("author")
            .prefetch_related("file_to_message__file")
        )
        return with_project_message_reads(
            messages, self.request.user.pk, include_reply=True
        )

    def post(self, request, *args, **kwargs):
        # TODO: try to create a message in a chat. If chat doesn't exist, create it and then create a message.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


@method_decorator(never_cache, name="dispatch")
class ChatMessageContext(GenericAPIView):
    permission_classes = [IsAuthenticated]
    chat_model = None

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                "direction",
                openapi.IN_QUERY,
                description="Направление загрузки",
                type=openapi.TYPE_STRING,
                enum=["around", "older", "newer"],
                default="around",
            ),
            openapi.Parameter(
                "limit",
                openapi.IN_QUERY,
                description="Количество сообщений с каждой стороны",
                type=openapi.TYPE_INTEGER,
                minimum=1,
                maximum=MAX_CONTEXT_LIMIT,
            ),
        ],
        responses={200: "Сообщения по порядку, older_than и newer_than для продолжения"},
    )
    def get(self, request, id, message_id):
        chat = get_accessible_chat(request.user, self.chat_model, id)
        form = MessageContextForm(request.query_params)
        if not form.is_valid():
            raise ValidationError(form.errors)
        queryset = chat.messages.select_related("author").prefetch_related(
            "file_to_message__file"
        )
        if isinstance(chat, ProjectChat):
            queryset = with_project_message_reads(
                queryset, request.user.pk, include_reply=True
            )
        else:
            queryset = queryset.select_related("reply_to__author")
        context = get_message_context(chat, queryset, message_id, **form.cleaned_data)
        return Response(
            {
                "results": self.get_serializer(context.messages, many=True).data,
                "older_than": context.older_than,
                "newer_than": context.newer_than,
            }
        )


MAX_SYNC_LIMIT = 100
MAX_SYNC_CURSOR = 2**63 - 1


class ChatMessageChangesForm(forms.Form):
    after = forms.IntegerField(min_value=0, max_value=MAX_SYNC_CURSOR)
    limit = forms.IntegerField(required=False, min_value=1, max_value=MAX_SYNC_LIMIT)


@method_decorator(never_cache, name="dispatch")
class ChatMessageChanges(GenericAPIView):
    permission_classes = [IsAuthenticated]
    chat_model = None

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                "after",
                openapi.IN_QUERY,
                description="Курсор из sync_cursor истории или next_cursor изменений",
                type=openapi.TYPE_INTEGER,
                required=True,
                minimum=0,
            ),
            openapi.Parameter(
                "limit",
                openapi.IN_QUERY,
                description="Количество изменений на странице",
                type=openapi.TYPE_INTEGER,
                minimum=1,
                maximum=MAX_SYNC_LIMIT,
                default=MAX_SYNC_LIMIT,
            ),
        ],
        responses={
            200: "Изменения, next_cursor и has_more",
            409: "Курсор устарел. Нужно заново загрузить историю.",
        },
    )
    def get(self, request, id):
        chat = get_accessible_chat(request.user, self.chat_model, id)
        form = ChatMessageChangesForm(request.query_params)
        if not form.is_valid():
            raise ValidationError(form.errors)
        after = form.cleaned_data["after"]
        limit = form.cleaned_data["limit"] or MAX_SYNC_LIMIT
        high_water = chat.message_revision
        if after > high_water:
            return Response(
                {"detail": "Курсор недействителен. Загрузите историю чата заново."},
                status=status.HTTP_409_CONFLICT,
            )

        changed = (
            chat.messages.filter(sync_revision__gt=after, sync_revision__lte=high_water)
            .order_by("sync_revision")
            .select_related("author")
            .prefetch_related("file_to_message__file")
        )
        if isinstance(chat, ProjectChat):
            changed = with_project_message_reads(
                changed, request.user.pk, include_reply=True
            )
        else:
            changed = changed.select_related("reply_to__author")
        page = list(changed[: limit + 1])
        has_more = len(page) > limit
        results = []
        for message in page[:limit]:
            if message.is_deleted:
                results.append({"type": "delete", "message_id": message.pk})
            else:
                results.append(
                    {
                        "type": "upsert",
                        "message_id": message.pk,
                        "message": self.get_serializer(message).data,
                    }
                )
        # A message may move past this watermark if edited during the read.
        # That newer revision will be fetched on the following request.
        return Response(
            {
                "results": results,
                "next_cursor": page[limit - 1].sync_revision if has_more else high_water,
                "has_more": has_more,
            }
        )


class ChatFileList(ListAPIView):
    serializer_class = ChatAttachmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        chat = get_accessible_chat(self.request.user, self.chat_model, self.kwargs["id"])
        return (
            chat_attachments(chat)
            .select_related("file", "direct_message", "project_message")
            .order_by("file__datetime_uploaded", "pk")
        )


class DirectChatFileList(ChatFileList):
    chat_model = DirectChat


class ProjectChatFileList(ChatFileList):
    chat_model = ProjectChat


@method_decorator(never_cache, name="dispatch")
class ChatAttachmentDownload(APIView):
    permission_classes = [IsAuthenticated]
    chat_model = None

    @swagger_auto_schema(
        produces=["application/octet-stream"],
        responses={
            200: openapi.Response("Файл", schema=openapi.Schema(type=openapi.TYPE_FILE)),
            404: "Вложение недоступно",
            502: "Хранилище недоступно",
        },
    )
    def get(self, request, id, message_id, attachment_id):
        chat = get_accessible_chat(request.user, self.chat_model, id)
        return download_chat_attachment(request, chat, message_id, attachment_id)


class HasChatUnreadsView(GenericAPIView):
    """Returns True if user has unread messages"""

    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        responses={
            200: openapi.Response(
                description="Gives you True or False whether user has unread messages or not",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "has_unreads": openapi.Schema(
                            type=openapi.TYPE_BOOLEAN,
                            description="True if user has unread messages",
                        )
                    },
                ),
            )
        }
    )
    def get(self, request, *args, **kwargs):
        user = request.user
        # get all user chats
        direct_messages = user.direct_chats.all().prefetch_related("messages")

        has_direct_messages_unread = (
            direct_messages.filter(messages__is_read=False)
            .exclude(messages__is_deleted=True)
            .distinct()
            .exists()
        )
        has_project_messages_unread = (
            unread_project_messages(user.pk)
            .filter(chat_id__in=user.get_project_chats().values("pk"))
            .exists()
        )
        return Response(
            {"has_unreads": has_direct_messages_unread or has_project_messages_unread}
        )
