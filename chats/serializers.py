from rest_framework import serializers

from chats.models import (
    DirectChat,
    ProjectChat,
    DirectChatMessage,
    ProjectChatMessage,
)
from chats.project_reads import project_message_is_read, with_project_message_reads
from files.serializers import UserFileSerializer
from users.serializers import UserListSerializer, UserDetailSerializer, UserChatSerializer


class DirectChatListSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()
    opponent = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField(read_only=True)
    image_address = serializers.SerializerMethodField(read_only=True)

    def get_opponent(self, chat: DirectChat):
        user = self.context.get("opponent")
        return UserChatSerializer(
            user, context={"request": self.context.get("request")}
        ).data

    def get_name(self, chat: DirectChat):
        user = self.context.get("opponent")
        return user.get_full_name()

    def get_image_address(self, chat: DirectChat):
        user = self.context.get("opponent")
        return user.avatar

    @classmethod
    def get_last_message(cls, chat: DirectChat):
        return DirectChatMessageListSerializer(chat.get_last_message()).data

    class Meta:
        model = DirectChat
        fields = ["id", "opponent", "last_message", "name", "image_address"]


class DirectChatDetailSerializer(serializers.ModelSerializer):
    opponent = serializers.SerializerMethodField()

    def get_opponent(self, chat: DirectChat):
        user = self.context.get("opponent")
        return UserChatSerializer(
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
    unread_count = serializers.IntegerField(read_only=True)
    first_unread_message_id = serializers.IntegerField(read_only=True, allow_null=True)

    @classmethod
    def get_image_address(cls, chat: ProjectChat):
        return chat.project.image_address

    @classmethod
    def get_name(cls, chat: ProjectChat):
        return chat.project.name

    def get_last_message(self, chat: ProjectChat):
        user_id = self.context["request"].user.pk
        messages = chat.messages.filter(is_deleted=False).order_by("-created_at", "-pk")
        message = with_project_message_reads(
            messages, user_id, include_reply=True
        ).first()
        return ProjectChatMessageListSerializer(message, context=self.context).data

    class Meta:
        model = ProjectChat
        fields = [
            "id",
            "project",
            "last_message",
            "image_address",
            "name",
            "unread_count",
            "first_unread_message_id",
        ]


class ProjectChatDetailSerializer(serializers.ModelSerializer):
    users = serializers.SerializerMethodField(read_only=True)
    name = serializers.SerializerMethodField(read_only=True)
    image_address = serializers.SerializerMethodField(read_only=True)
    unread_count = serializers.IntegerField(read_only=True)
    first_unread_message_id = serializers.IntegerField(read_only=True, allow_null=True)

    @classmethod
    def get_image_address(cls, chat: ProjectChat):
        return chat.project.image_address

    @classmethod
    def get_name(cls, chat: ProjectChat):
        return chat.project.name

    def get_users(self, chat: ProjectChat):
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
            "unread_count",
            "first_unread_message_id",
        ]


class ChatReplySerializer(serializers.ModelSerializer):
    def get_attribute(self, message):
        reply = super().get_attribute(message)
        if reply is not None and (reply.is_deleted or reply.chat_id != message.chat_id):
            return None
        return reply


class DirectChatMessageSerializer(ChatReplySerializer):
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
    # author = UserDetailSerializer()
    author = UserChatSerializer()
    reply_to = DirectChatMessageSerializer(allow_null=True)
    files = serializers.SerializerMethodField()

    @classmethod
    def get_files(cls, message: DirectChatMessage):
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
            "client_message_id",
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
    is_read = serializers.SerializerMethodField()
    read_count = serializers.IntegerField(read_only=True, default=0)

    def get_is_read(self, message) -> bool:
        request = self.context.get("request")
        return project_message_is_read(
            legacy_read=message.is_read,
            is_author=request is not None and message.author_id == request.user.pk,
            read_by_me=getattr(message, "read_by_me", False),
            read_count=getattr(message, "read_count", 0),
        )

    class Meta:
        model = ProjectChatMessage
        fields = [
            "id",
            "author",
            "text",
            "reply_to",
            "is_edited",
            "is_read",
            "read_count",
            "is_deleted",
            "created_at",
        ]


class ProjectChatReplySerializer(ProjectChatMessageSerializer, ChatReplySerializer):
    pass


class ProjectChatMessageListSerializer(ProjectChatMessageSerializer):
    reply_to = ProjectChatReplySerializer(allow_null=True)
    files = serializers.SerializerMethodField()

    @classmethod
    def get_files(cls, message: ProjectChatMessage):
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
            "client_message_id",
            "files",
            "reply_to",
            "is_edited",
            "is_read",
            "read_count",
            "is_deleted",
            "created_at",
        ]
