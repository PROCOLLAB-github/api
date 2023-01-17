from rest_framework.generics import ListAPIView

from rest_framework.permissions import IsAuthenticated

from chats.serializers import (
    DirectChatListSerializer,
    DirectChatMessageListSerializer,
    ProjectChatListSerializer,
    ProjectChatMessageListSerializer,
)


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
        return user.project_chats.all()


class DirectChatMessageList(ListAPIView):
    serializer_class = DirectChatMessageListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.request.user.direct_chats.get(
            id=self.kwargs["chat_id"]
        ).messages.all()


class ProjectChatMessageList(ListAPIView):
    serializer_class = ProjectChatMessageListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.request.user.project_chats.get(
            id=self.kwargs["chat_id"]
        ).messages.all()


# class MessageDetail(generics.RetrieveUpdateDestroyAPIView):
#     queryset = Message.objects.all()
#     serializer_class = MessageSerializer
#     permission_classes = [IsMessageOwner]

#     def patch(self, request, *args, **kwargs):
#         message = Message.objects.get(pk=self.kwargs["message_id"])

#         if request.user != message.author:
#             return Response(status=status.HTTP_403_FORBIDDEN)

#         return self.partial_update(request, *args, **kwargs)

#     def delete(self, request, *args, **kwargs):
#         message = Message.objects.get(pk=self.kwargs["message_id"])

#         if request.user != message.author:
#             return Response(status=status.HTTP_403_FORBIDDEN)

#         return self.destroy(request, *args, **kwargs)

#     def put(self, request, *args, **kwargs):
#         message = Message.objects.get(pk=self.kwargs["message_id"])

#         if request.user != message.author:
#             return Response(status=status.HTTP_403_FORBIDDEN)

#         return self.update(request, *args, **kwargs)
