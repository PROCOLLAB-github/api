from rest_framework import serializers
from rest_framework.serializers import ModelSerializer

from chats.models import (
    DirectChat,
    ProjectChat,
    DirectChatMessage,
    ProjectChatMessage,
    DirectChatAttachment,
    ProjectChatAttachment,
)
from users.serializers import UserListSerializer


class DirectChatListSerializer(ModelSerializer):
    last_message = serializers.SerializerMethodField()
    users = serializers.SerializerMethodField(read_only=True)

    @classmethod
    def get_users(cls, chat: ProjectChat):
        return UserListSerializer(chat.get_users(), many=True).data

    @classmethod
    def get_last_message(cls, chat: DirectChat):
        return DirectChatMessageListSerializer(chat.get_last_message()).data

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


class ProjectChatListSerializer(ModelSerializer):
    last_message = serializers.SerializerMethodField(read_only=True)

    @classmethod
    def get_last_message(cls, chat: ProjectChat):
        return ProjectChatMessageListSerializer(chat.get_last_message()).data

    class Meta:
        model = ProjectChat
        fields = ["id", "project", "last_message"]


class ProjectChatDetailSerializer(ModelSerializer):
    users = serializers.SerializerMethodField(read_only=True)
    name = serializers.SerializerMethodField(read_only=True)
    image_address = serializers.SerializerMethodField(read_only=True)

    @classmethod
    def get_image_address(cls, chat: ProjectChat):
        return chat.project.image_address

    @classmethod
    def get_name(cls, chat: ProjectChat):
        return chat.project.name

    @classmethod
    def get_users(cls, chat: ProjectChat):
        return UserListSerializer(chat.get_users(), many=True).data

    class Meta:
        model = ProjectChat
        fields = [
            "id",
            "name",
            "image_address",
            "messages",
            "users",
        ]


class DirectChatMessageListSerializer(ModelSerializer):
    class Meta:
        model = DirectChatMessage
        fields = [
            "id",
            "author",
            "text",
            "reply_to",
            "created_at",
        ]


class ProjectChatMessageListSerializer(ModelSerializer):
    class Meta:
        model = ProjectChatMessage
        fields = [
            "id",
            "author",
            "text",
            "reply_to",
            "created_at",
        ]


class DirectChatAttachmentSerializer(ModelSerializer):
    class Meta:
        model = DirectChatAttachment
        fields = [
            "user",
            "link",
            "name",
            "extension",
            "chat_id",
            "size",
            "datetime_uploaded",
        ]


class ProjectChatAttachmentSerializer(ModelSerializer):
    class Meta:
        model = ProjectChatAttachment
        fields = [
            "user",
            "link",
            "name",
            "extension",
            "chat_id",
            "size",
            "datetime_uploaded",
        ]
