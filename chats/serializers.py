from rest_framework import serializers

from chats.models import BaseChat


class ChatListSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()

    @classmethod
    def get_last_message(cls, chat: BaseChat):
        return chat.get_last_message()

    class Meta:
        model = BaseChat
        fields = ["id", "users", "last_message"]


# class MessageInChatSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Message
#         fields = [
#             "id",
#             "text",
#             "author",
#             "created_at",
#         ]
#
#
# class ChatDetailSerializer(serializers.ModelSerializer):
#     messages = MessageInChatSerializer(many=True, read_only=True)
#
#     class Meta:
#         model = Chat
#         fields = [
#             "id",
#             "name",
#             "users",
#             "messages",
#         ]
#
#
# class MessageSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Message
#         fields = [
#             "id",
#             "chat",
#             "author",
#             "text",
#             "created_at",
#         ]
#
#     def create(self, validated_data):
#         chat_id = self.context["request"].data["chat"]
#         chat = Chat.objects.get(id=chat_id)
#         message = Message.objects.create(chat=chat, **validated_data)
#         return message
