# from rest_framework import serializers
#
# from chats.models import Chat, Message
#
#
# class ChatSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Chat
#         fields = [
#             "id",
#             "name",
#             "users",
#         ]
#
#
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
