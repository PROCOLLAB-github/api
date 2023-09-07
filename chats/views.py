from django.contrib.auth import get_user_model

from rest_framework import status
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
)

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from chats.models import ProjectChat, DirectChat
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
from files.serializers import UserFileSerializer

User = get_user_model()


class DirectChatList(ListAPIView):
    serializer_class = DirectChatListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return user.direct_chats.all()


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
            assert "_" in self.kwargs["pk"], "pk must contain underscore"

            user1_id, user2_id = map(int, self.kwargs["pk"].split("_"))

            assert (
                request.user.id == user1_id or request.user.id == user2_id
            ), "current user id is not present in pk"

            user1 = User.objects.get(pk=user1_id)
            user2 = User.objects.get(pk=user2_id)

            data = DirectChatDetailSerializer(DirectChat.get_chat(user1, user2)).data

            if user1 == request.user:
                # may be is better to use serializer or return dict -
                # {"first_name": user2.first_name, "last_name": user2.last_name}
                data["name"] = f"{user2.first_name} {user2.last_name}"
                data["image_address"] = user2.avatar
            else:
                data["name"] = f"{user1.first_name} {user1.last_name}"
                data["image_address"] = user1.avatar

            return Response(
                status=status.HTTP_200_OK,
                data=data,
            )

        except ValueError:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"detail": "pk must contain two integers separated by underscore"},
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
            self.request.user.direct_chats.get(id=self.kwargs["pk"])
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
                ProjectChat.objects.get(id=self.kwargs["pk"])
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
        messages = self.request.user.direct_chats.get(id=self.kwargs["pk"]).messages.all()

        return get_all_files(messages)


class ProjectChatFileList(ListCreateAPIView):
    serializer_class = UserFileSerializer
    permission_classes = [IsProjectChatMember]

    def get_queryset(self):
        messages = ProjectChat.objects.get(id=self.kwargs["pk"]).messages.all()

        return get_all_files(messages)
