from rest_framework import generics, permissions, mixins, status
from rest_framework.response import Response

from chats.models import Chat, Message
from chats.serializers import ChatSerializer, MessageSerializer, ChatDetailSerializer


class ChatList(generics.ListCreateAPIView):
    queryset = Chat.objects.all()
    serializer_class = ChatSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class ChatDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ChatDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return (
            Chat.objects.all()
            .prefetch_related("messages")
            .prefetch_related("users")
            .all()
        )

    def get(self, request, *args, **kwargs):
        """
        Get chat by id
        You can set first_obj and count to get messages from chat
        Args:
            request: request
            *args: args
            **kwargs: kwargs

        Returns:
            Response with chat
        """

        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class MessageList(
    mixins.ListModelMixin, mixins.CreateModelMixin, generics.GenericAPIView
):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = MessageSerializer

    def get_queryset(self):
        return Message.objects.p.filter(chat_id=self.kwargs["pk"])

    def post(self, request, *args, **kwargs):
        try:
            request.data["chat"] = str(self.kwargs["pk"])
        except AttributeError:
            pass

        chat = Chat.objects.get(pk=request.data["chat"])
        if request.user not in chat.users.all():
            return Response(status=status.HTTP_403_FORBIDDEN)

        return self.create(request, *args, **kwargs)


class MessageDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def patch(self, request, *args, **kwargs):
        message = Message.objects.get(pk=self.kwargs["message_id"])
        if request.user != message.author:
            return Response(status=status.HTTP_403_FORBIDDEN)
        return self.partial_update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        message = Message.objects.get(pk=self.kwargs["message_id"])

        if request.user != message.author:
            return Response(status=status.HTTP_403_FORBIDDEN)
        return self.destroy(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        message = Message.objects.get(pk=self.kwargs["message_id"])

        if request.user != message.author:
            return Response(status=status.HTTP_403_FORBIDDEN)

        return self.update(request, *args, **kwargs)
