from django.contrib.auth import get_user_model
from django.db.models import Q

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
from rest_framework.response import Response

from chats.models import ProjectChat, DirectChat, DirectChatMessage, ProjectChatMessage
from chats.pagination import MessageListPagination
from chats.permissions import IsProjectChatMember
from chats.serializers import (
    DirectChatListSerializer,
    DirectChatMessageListSerializer,
    ProjectChatListSerializer,
    ProjectChatMessageListSerializer,
    ProjectChatDetailSerializer,
    DirectChatDetailSerializer,
)
from chats.utils import get_all_files
from files.models import UserFile
from files.serializers import UserFileSerializer

User = get_user_model()


class DirectChatList(ListAPIView):
    serializer_class = DirectChatListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return user.direct_chats.all()

    def get(self, request, *args, **kwargs):
        chats = self.get_queryset()
        serialized_chats = []
        chats_users_ids = [[int(num) for num in chat.pk.split("_")] for chat in chats]
        all_chats_users = User.objects.filter(pk__in=sum(chats_users_ids, []))
        for user1_id, user2_id in chats_users_ids:
            # fixme: move to function like get_user() and get_opponent()
            chat = chats.get(id=f"{user1_id}_{user2_id}")

            try:
                user1 = all_chats_users.get(pk=user1_id)
                user2 = all_chats_users.get(pk=user2_id)
            except User.DoesNotExist:
                # fixme: show deleted profile
                continue

            if user1 == request.user:
                opponent = user2
            else:  # fixme: if user1 == user2
                opponent = user1

            context = {"opponent": opponent}
            serialized_chat = DirectChatListSerializer(chat, context=context).data
            serialized_chats.append(serialized_chat)
        return Response(serialized_chats, status=status.HTTP_200_OK)


class ProjectChatList(ListAPIView):
    serializer_class = ProjectChatListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return user.get_project_chats()


class ProjectChatDetail(RetrieveAPIView):
    queryset = ProjectChat.objects.all()
    serializer_class = ProjectChatDetailSerializer
    permission_classes = [IsProjectChatMember]


class DirectChatDetail(RetrieveAPIView):
    queryset = DirectChat.objects.all()
    serializer_class = DirectChatDetailSerializer
    permission_classes = [IsAuthenticated]

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


class DirectChatMessageList(ListCreateAPIView):
    serializer_class = DirectChatMessageListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = MessageListPagination

    def get_queryset(self):
        return (
            self.request.user.direct_chats.get(id=self.kwargs["id"])
            .messages.filter(is_deleted=False)
            .order_by("-created_at")
            .all()
        )


class ProjectChatMessageList(ListCreateAPIView):
    serializer_class = ProjectChatMessageListSerializer
    permission_classes = [IsProjectChatMember]
    pagination_class = MessageListPagination

    def get_queryset(self):
        try:
            return (
                ProjectChat.objects.get(id=self.kwargs["id"])
                .messages.filter(is_deleted=False)
                .order_by("-created_at")
                .all()
            )
        except ProjectChat.DoesNotExist:
            return ProjectChat.objects.none()

    def post(self, request, *args, **kwargs):
        # TODO: try to create a message in a chat. If chat doesn't exist, create it and then create a message.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class DirectChatFileList(ListCreateAPIView):
    serializer_class = UserFileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):

        messages = self.request.user.direct_chats.get(id=self.kwargs["id"]).messages.all()

        return get_all_files(messages)


class ProjectChatFileList(ListCreateAPIView):
    serializer_class = UserFileSerializer
    permission_classes = [IsProjectChatMember]

    def get_queryset(self):
        try:
            messages = ProjectChat.objects.get(id=self.kwargs["id"]).messages.all()
            return get_all_files(messages)
        except ProjectChat.DoesNotExist:
            return UserFile.objects.none()


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

        unread_dir_messages = (
            DirectChatMessage.objects.filter(chat__users=user, is_read=False)
            .exclude(Q(author=user) | Q(is_deleted=True))
            .distinct()
            .exists()
        )

        unread_proj_messages = (
            ProjectChatMessage.objects.filter(is_read=False)
            .exclude(is_deleted=True)
            .distinct()
            .exists()
        )
        return Response({"has_unreads": unread_proj_messages or unread_dir_messages})
