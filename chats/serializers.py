from rest_framework import serializers

from chats.models import (
    DirectChat,
    ProjectChat,
    DirectChatMessage,
    ProjectChatMessage,
)
from files.serializers import UserFileSerializer
from users.serializers import UserListSerializer, UserDetailSerializer


class DirectChatListSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()
    opponent = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField(read_only=True)
    image_address = serializers.SerializerMethodField(read_only=True)

    def get_opponent(self, chat: DirectChat) -> dict:
        user = self.context.get("opponent")
        return UserDetailSerializer(
            user, context={"request": self.context.get("request")}
        ).data

    def get_name(self, chat: DirectChat) -> str:
        user = self.context.get("opponent")
        return user.get_full_name()

    def get_image_address(self, chat: DirectChat) -> str:
        user = self.context.get("opponent")
        return user.avatar

    @classmethod
    def get_last_message(cls, chat: DirectChat) -> dict:
        return DirectChatMessageListSerializer(chat.get_last_message()).data

    class Meta:
        model = DirectChat
        fields = ["id", "opponent", "last_message", "name", "image_address"]


class DirectChatDetailSerializer(serializers.ModelSerializer):
    opponent = serializers.SerializerMethodField()

    def get_opponent(self, chat: DirectChat) -> dict:
        user = self.context.get("opponent")
        return UserDetailSerializer(
            user, context={"request": self.context.get("request")}
        ).data

    class Meta:
        model = DirectChat
        fields = [
            "id",
            "opponent",
        ]


class ProjectChatListSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField(read_only=True)
    name = serializers.SerializerMethodField(read_only=True)
    image_address = serializers.SerializerMethodField(read_only=True)

    @classmethod
    def get_image_address(cls, chat: ProjectChat) -> str:
        return chat.project.image_address

    @classmethod
    def get_name(cls, chat: ProjectChat) -> str:
        return chat.project.name

    @classmethod
    def get_last_message(cls, chat: ProjectChat) -> dict:
        return ProjectChatMessageListSerializer(chat.get_last_message()).data

    class Meta:
        model = ProjectChat
        fields = ["id", "project", "last_message", "image_address", "name"]


class ProjectChatDetailSerializer(serializers.ModelSerializer):
    users = serializers.SerializerMethodField(read_only=True)
    name = serializers.SerializerMethodField(read_only=True)
    image_address = serializers.SerializerMethodField(read_only=True)

    @classmethod
    def get_image_address(cls, chat: ProjectChat) -> str:
        return chat.project.image_address

    @classmethod
    def get_name(cls, chat: ProjectChat) -> str:
        return chat.project.name

    def get_users(self, chat: ProjectChat) -> dict:
        return UserListSerializer(
            chat.get_users(), context={"request": self.context.get("request")}, many=True
        ).data

    class Meta:
        model = ProjectChat
        fields = [
            "id",
            "name",
            "image_address",
            "users",
        ]


class DirectChatMessageSerializer(serializers.ModelSerializer):
    """Same as DirectChatMessageListSerializer but reply_to is an id, not an object.
    This is done to avoid circular imports.
    """

    author = UserDetailSerializer()

    class Meta:
        model = DirectChatMessage
        fields = [
            "id",
            "author",
            "text",
            "reply_to",
            "is_edited",
            "is_read",
            "is_deleted",
            "created_at",
        ]


class DirectChatMessageListSerializer(serializers.ModelSerializer):
    author = UserDetailSerializer()
    reply_to = DirectChatMessageSerializer(allow_null=True)
    files = serializers.SerializerMethodField()

    @classmethod
    def get_files(cls, message: DirectChatMessage) -> list[dict]:
        data = []
        for file_to_message in message.file_to_message.all():
            file_data = UserFileSerializer(file_to_message.file).data
            data.append(file_data)
        return data

    class Meta:
        model = DirectChatMessage
        fields = [
            "id",
            "author",
            "text",
            "reply_to",
            "files",
            "is_edited",
            "is_read",
            "is_deleted",
            "created_at",
        ]


class ProjectChatMessageSerializer(serializers.ModelSerializer):
    """Same as ProjectChatMessageListSerializer but reply_to is an id, not an object.
    This is done to avoid circular imports.
    """

    author = UserDetailSerializer()

    class Meta:
        model = ProjectChatMessage
        fields = [
            "id",
            "author",
            "text",
            "reply_to",
            "is_edited",
            "is_read",
            "is_deleted",
            "created_at",
        ]


class ProjectChatMessageListSerializer(serializers.ModelSerializer):
    author = UserDetailSerializer()
    reply_to = ProjectChatMessageSerializer(allow_null=True)
    files = serializers.SerializerMethodField()

    @classmethod
    def get_files(cls, message: DirectChatMessage) -> dict:
        data = []
        for file_to_message in message.file_to_message.all():
            file_data = UserFileSerializer(file_to_message.file).data
            data.append(file_data)
        return data

    class Meta:
        model = ProjectChatMessage
        fields = [
            "id",
            "author",
            "text",
            "files",
            "reply_to",
            "is_edited",
            "is_read",
            "is_deleted",
            "created_at",
        ]
