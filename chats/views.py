from django.contrib.auth import get_user_model

# from django.db import transaction
from rest_framework import status
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    # GenericAPIView,
    # get_object_or_404,
)

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from chats.models import ProjectChat, DirectChat
from chats.serializers import (
    DirectChatListSerializer,
    DirectChatMessageListSerializer,
    ProjectChatListSerializer,
    ProjectChatMessageListSerializer,
    ProjectChatDetailSerializer,
    DirectChatDetailSerializer,
)

# from files.helpers import FileAPI, get_file_data

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
    permission_classes = [IsAuthenticated]


class DirectChatDetail(RetrieveAPIView):
    queryset = DirectChat.objects.all()
    serializer_class = DirectChatDetailSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs) -> Response:
        try:
            assert "_" in self.kwargs["pk"], "pk must contain underscore"

            user1_id, user2_id = map(int, self.kwargs["pk"].split("_"))

            user1 = User.objects.get(pk=user1_id)
            user2 = User.objects.get(pk=user2_id)

            data = DirectChatDetailSerializer(DirectChat.get_chat(user1, user2)).data

            if user1 == request.user:
                # may be is better to use serializer or return dict
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

    def get_queryset(self):
        return (
            self.request.user.direct_chats.get(id=self.kwargs["pk"])
            .messages.filter(is_deleted=False)
            .all()
        )


class ProjectChatMessageList(ListCreateAPIView):
    serializer_class = ProjectChatMessageListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            ProjectChat.objects.get(id=self.kwargs["pk"])
            .messages.filter(is_deleted=False)
            .all()
        )

    def post(self, request, *args, **kwargs):
        # TODO: try to create a message in a chat. If chat doesn't exist, create it and then create a message.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


# class ChatAttachmentView(GenericAPIView):
#     permission_classes = [IsAuthenticatedOrReadOnly]
#     serializer_class = ChatAttachmentSerializer
#     queryset = ChatAttachment.objects.all()
#
#     @transaction.atomic
#     def post(self, request):
#         """creates a UserFile object and uploads the file to selectel"""
#
#         file = request.FILES["file"]
#         file_api = FileAPI(file, request.user)
#         status_code, url = file_api.upload()
#
#         if status_code == 201:
#             file_data = get_file_data(file)
#             ChatAttachment.objects.create(
#                 user=request.user,
#                 link=url,
#                 name=file_data["name"],
#                 extension=file_data["extension"],
#                 size=file_data["size"],
#             )
#
#         return Response("Failed to upload file", status=status.HTTP_409_CONFLICT)
#
#     def delete(self, request, *args, **kwargs):
#         """deletes the file (only if the request is sent by the user who owns it!)
#         The link has to be specified in the JSON body, not in the URL arguments.
#         """
#         # get the link from the query
#         if request.query_params and (request.query_params.get("link") is not None):
#             link = request.query_params.get("link")
#         else:
#             return Response(
#                 {
#                     "error": "you have to pass the link of the object you want to delete in query parameters"
#                 },
#                 status=status.HTTP_400_BAD_REQUEST,
#             )
#         instance = get_object_or_404(self.get_queryset(), link=link)
#         if instance.user != request.user:
#             return Response(status=status.HTTP_403_FORBIDDEN)
#         FileAPI.delete(instance.link)  # delete the file via api
#         instance.delete()  # delete the UserFile object
#         return Response(status=status.HTTP_204_NO_CONTENT)
