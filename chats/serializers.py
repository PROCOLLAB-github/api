from rest_framework import serializers

from chats.models import DirectChat, ProjectChat, DirectChatMessage, ProjectChatMessage
from users.serializers import UserListSerializer


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
        fields = [
            "id",
            "users",
            "last_message",
        ]


class DirectChatDetailSerializer(serializers.ModelSerializer):
    users = serializers.SerializerMethodField(read_only=True)

    @classmethod
    def get_users(cls, chat: ProjectChat):
        return UserListSerializer(chat.get_users(), many=True).data

    class Meta:
        model = DirectChat
        fields = [
            "id",
            "users",
            "messages",
        ]


class ProjectChatListSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField(read_only=True)

    @classmethod
    def get_last_message(cls, chat: ProjectChat):
        return chat.get_last_message()

    class Meta:
        model = ProjectChat
        fields = ["id", "project", "last_message"]


class ProjectChatDetailSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField(read_only=True)
    users = serializers.SerializerMethodField(read_only=True)

    @classmethod
    def get_users(cls, chat: ProjectChat):
        return UserListSerializer(chat.get_users(), many=True).data

    @classmethod
    def get_last_message(cls, chat: ProjectChat):
        return chat.get_last_message()

    class Meta:
        model = ProjectChat
        fields = [
            "id",
            "project",
            "last_message",
            "users",
        ]


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
