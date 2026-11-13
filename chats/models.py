from abc import abstractmethod
from hashlib import sha256
from typing import List

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, router, transaction

from files.models import UserFile
from projects.models import Project

User = get_user_model()


class BaseChat(models.Model):
    """
    Base Chat model

    Attributes:
        created_at: A DateTimeField indicating date of creation.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    message_revision = models.PositiveBigIntegerField(
        default=0, db_default=0, editable=False
    )

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        if not self._state.adding and update_fields is None:
            # A chat settings save must not overwrite a newer message cursor.
            update_fields = {
                field.attname
                for field in self._meta.concrete_fields
                if not field.primary_key
                and field.name != "message_revision"
                and field.attname not in self.get_deferred_fields()
            }
        return super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def visible_messages(self):
        return self.messages.filter(is_deleted=False).order_by("-created_at", "-pk")

    def get_users_str(self):
        """Returns string of users separated by a comma, who are in chat

        Returns:
            str: string of users, who are in chat
        """
        users = self.get_users()
        return ", ".join([user.get_full_name() for user in users])

    @abstractmethod
    def get_users(self):
        """
        Returns all collaborators and leader of the project.

        Returns:
            List[CustomUser]: list of users, who are collaborators or leader of the project
        """
        pass

    @abstractmethod
    def get_avatar(self, user):
        """
        Returns avatar of the chat for given user

        Args:
            user: User who will see the avatar

        Returns:
            str: link to avatar of the chat for given user
        """
        pass

    @abstractmethod
    def get_last_messages(self, message_count):
        """
        Returns last messages of the chat

        Args:
            message_count: number of messages to return

        Returns:
            List[Message]: list of messages
        """
        pass

    def __str__(self):
        return f"BaseChat<{self.pk}>"

    class Meta:
        abstract = True


class ProjectChat(BaseChat):
    """
    ProjectChat model

    Attributes:
        project: A ForeignKey to Project model, indicating project, which chat belongs to.
        created_at: A DateTimeField indicating date of creation.
    """

    id = models.PositiveIntegerField(primary_key=True, unique=True)
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="project_chats"
    )

    def get_users(self):
        collaborators = self.project.collaborator_set.all()
        users = [collaborator.user for collaborator in collaborators]
        return users + [self.project.leader]

    def get_avatar(self, user):
        return self.project.image_address

    def get_last_messages(self, message_count) -> List["BaseMessage"]:
        return self.visible_messages()[:message_count]

    def __str__(self):
        return f"ProjectChat<{self.project.id}> - {self.project.name}"

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        self.id = self.project.id
        super().save(force_insert, force_update, using, update_fields)

    class Meta:
        verbose_name = "Чат проекта"
        verbose_name_plural = "Чаты проектов"


class DirectChat(BaseChat):
    """
    DirectChat model

    Attributes:
        created_at: A DateTimeField indicating date of creation.

    Methods:
        get_users: returns list of users, who are in chat
    """

    id = models.CharField(primary_key=True, max_length=64)
    users = models.ManyToManyField(User, related_name="direct_chats")

    def get_users(self):
        return self.users.all()

    def get_avatar(self, user):
        other_user = self.get_users().exclude(pk=user.pk).first()
        return other_user.avatar

    @classmethod
    @transaction.atomic
    def get_chat(cls, user1, user2) -> "DirectChat":
        """
        Returns chat between two users.

        Args:
            user1 (CustomUser): first user, who is in chat
            user2 (CustomUser): second user, who is in chat

        Returns:
            DirectChat: chat between two users
        """

        pk = cls.get_chat_id_from_users(user1, user2)
        chat, created = cls.objects.get_or_create(pk=pk)
        if created:
            chat.users.set([user1, user2])
        return chat

    def get_last_messages(self, message_count):
        return self.visible_messages()[:message_count]

    def get_other_user(self, user) -> User:
        return self.users.exclude(pk=user.pk).first()

    @classmethod
    def get_chat_id_from_users(cls, user1, user2):
        first_user = user1 if user1.pk < user2.pk else user2
        second_user = user2 if user1.pk < user2.pk else user1
        return f"{first_user.pk}_{second_user.pk}"

    def __str__(self):
        return f"DirectChat with {self.get_users_str()}"

    class Meta:
        verbose_name = "Личный чат"
        verbose_name_plural = "Личные чаты"


class BaseMessage(models.Model):
    """
    Base message model

    Attributes:
        text: A TextField containing message text.
        is_read: A BooleanField indicating whether message is read.
        is_deleted: A BooleanField indicating whether message is deleted.
        created_at: A DateTimeField indicating date of creation.
    """

    text = models.TextField(max_length=8192)
    is_read = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    client_message_id = models.UUIDField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    sync_revision = models.PositiveBigIntegerField(null=True, editable=False)

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        if update_fields is not None and not {
            "text",
            "is_deleted",
            "is_edited",
            "reply_to",
            "reply_to_id",
        }.intersection(update_fields):
            return super().save(
                force_insert=force_insert,
                force_update=force_update,
                using=using,
                update_fields=update_fields,
            )
        chat_model = self._meta.get_field("chat").related_model
        using = using or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            chats = chat_model.objects.using(using)
            # Serialize the revision with the message write in the same transaction.
            chat = chats.select_for_update().get(pk=self.chat_id)
            self.sync_revision = chat.message_revision + 1
            chats.filter(pk=chat.pk).update(message_revision=self.sync_revision)
            if update_fields is not None:
                update_fields = {*update_fields, "sync_revision"}
            return super().save(
                force_insert=force_insert,
                force_update=force_update,
                using=using,
                update_fields=update_fields,
            )

    def __str__(self):
        return f"Message<{self.pk}>"

    class Meta:
        verbose_name = "Сообщение"
        verbose_name_plural = "Сообщения"
        ordering = ["-created_at"]
        abstract = True


class ProjectChatMessage(BaseMessage):
    """
    ProjectMessage model

    Attributes:
        chat: A ForeignKey to ProjectChat model, indicating chat, which message belongs to.
        author: A ForeignKey referring to the User model.
        text: A TextField containing message text.
        created_at: A DateTimeField indicating date of creation.
    """

    chat = models.ForeignKey(
        ProjectChat, on_delete=models.CASCADE, related_name="messages"
    )
    author = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="project_messages"
    )
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="project_replies",
    )

    def clean(self):
        # check that replied message is in the same chat
        if self.reply_to and self.reply_to.chat != self.chat:
            raise ValidationError("Reply to message from another chat")

    def __str__(self):
        return f"ProjectChatMessage<{self.pk}>"

    class Meta:
        verbose_name = "Сообщение в чате проекта"
        verbose_name_plural = "Сообщения в чатах проектов"
        indexes = [
            models.Index(fields=["chat", "sync_revision"], name="project_chat_sync_idx")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["chat", "author", "client_message_id"],
                condition=models.Q(client_message_id__isnull=False),
                name="unique_project_chat_client_message",
            )
        ]


class ProjectChatMessageRead(models.Model):
    message = models.ForeignKey(
        ProjectChatMessage, on_delete=models.CASCADE, related_name="read_receipts"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        verbose_name = "Прочтение сообщения в чате проекта"
        verbose_name_plural = "Прочтения сообщений в чатах проектов"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "user"], name="unique_project_chat_message_reader"
            )
        ]


class DirectChatMessage(BaseMessage):
    """
    DirectChatMessage model

    Attributes:
        chat: A ForeignKey to DirectChat model, indicating chat, which message belongs to.
        author: A ForeignKey referring to the User model.
        text: A TextField containing message text.
        created_at: A DateTimeField indicating date of creation.
    """

    chat = models.ForeignKey(
        DirectChat, on_delete=models.CASCADE, related_name="messages"
    )
    author = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="direct_messages"
    )
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="direct_replies",
    )

    def clean(self):
        # check that replied message is in the same chat
        if self.reply_to and self.reply_to.chat != self.chat:
            raise ValidationError("Reply to message from another chat")

    def __str__(self):
        return f"DirectChatMessage<{self.pk}>"

    class Meta:
        verbose_name = "Сообщение в личном чате"
        verbose_name_plural = "Сообщения в личных чатах"
        indexes = [
            models.Index(fields=["chat", "sync_revision"], name="direct_chat_sync_idx")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["chat", "author", "client_message_id"],
                condition=models.Q(client_message_id__isnull=False),
                name="unique_direct_chat_client_message",
            )
        ]


class FileToMessage(models.Model):
    file = models.OneToOneField(
        UserFile,
        on_delete=models.CASCADE,
        related_name="file_to_message",
        primary_key=True,
        null=False,
    )
    direct_message = models.ForeignKey(
        DirectChatMessage,
        on_delete=models.CASCADE,
        related_name="file_to_message",
        null=True,
    )
    project_message = models.ForeignKey(
        ProjectChatMessage,
        on_delete=models.CASCADE,
        related_name="file_to_message",
        null=True,
    )

    @property
    def download_id(self):
        return sha256(self.file_id.encode()).hexdigest()

    @property
    def is_linked_to_one_message(self):
        return (self.direct_message_id is None) != (self.project_message_id is None)

    def __str__(self):
        return f"FileToMessage<{self.file}>"

    class Meta:
        verbose_name = "Связка файла и сообщения"
        verbose_name_plural = "Связки файлов и сообщений"
