from rest_framework import serializers

from chats.models import DirectChat, ProjectChat, DirectChatMessage, ProjectChatMessage


class DirectChatListSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()
    users = serializers.SerializerMethodField(read_only=True)

    @classmethod
    def get_users(cls, chat: ProjectChat):
        return chat.get_users()

    @classmethod
    def get_last_message(cls, chat: DirectChat):
        return chat.get_last_message()

    class Meta:
        model = DirectChat
        fields = ["id", "users", "last_message"]


class ProjectChatListSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField(read_only=True)
    users = serializers.SerializerMethodField(read_only=True)

    @classmethod
    def get_users(cls, chat: ProjectChat):
        return chat.get_users()

    @classmethod
    def get_last_message(cls, chat: ProjectChat):
        return chat.get_last_message()

    class Meta:
        model = ProjectChat
        fields = ["id", "project", "last_message"]


class DirectChatMessageListSerializer(serializers.ModelSerializer):
    class Meta:
        model = DirectChatMessage
        fields = [
            "id",
            "author",
            "text",
            "reply_to",
            "created_at",
        ]


class ProjectChatMessageListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectChatMessage
        fields = [
            "id",
            "author",
            "text",
            "reply_to",
            "created_at",
        ]
