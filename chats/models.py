from abc import abstractmethod
from typing import List

from django.contrib.auth import get_user_model
from django.db import models

from projects.models import Project

User = get_user_model()

id = models.AutoField(primary_key=True)


class BaseChat(models.Model):
    """
    Base Chat model

    Attributes:
        created_at: A DateTimeField indicating date of creation.
    """

    created_at = models.DateTimeField(auto_now_add=True)

    def get_last_message(self):
        return self.messages.last()

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
        return self.messages.order_by("-created_at")[:message_count]

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
    def get_chat(cls, user1, user2) -> "DirectChat":
        """
        Returns chat between two users.

        Args:
            user1 (CustomUser): first user, who is in chat
            user2 (CustomUser): second user, who is in chat

        Returns:
            DirectChat: chat between two users
        """
        # TODO: use .get_or_create() here
        try:
            return cls.objects.get(pk="_".join(sorted([str(user1.pk), str(user2.pk)])))
        except cls.DoesNotExist:
            chat = cls.objects.create(pk="_".join(sorted([str(user1.pk), str(user2.pk)])))
            chat.users.set([user1, user2])
            return chat

    def get_last_messages(self, message_count):
        return self.messages.order_by("-created_at")[:message_count]

    def get_other_user(self, user):
        return self.users.exclude(pk=user.pk).first()

    @classmethod
    def create_from_two_users(cls, user1, user2):
        chat = cls.objects.create(pk=cls.get_chat_id_from_users(user1, user2))
        chat.users.set([user1, user2])
        return chat

    @classmethod
    def get_chat_id_from_users(cls, user1, user2):
        first_user = user1 if user1.pk < user2.pk else user2
        second_user = user2 if user1.pk < user2.pk else user1
        return f"{first_user.pk}_{second_user.pk}"

    # def save(
    #     self, force_insert=False, force_update=False, using=None, update_fields=None
    # ):
    #     self.id = self.get_chat_id_from_users(*self.users.all())
    #     super().save(force_insert, force_update, using, update_fields)

    def __str__(self):
        return f"DirectChat with {self.get_users_str()}"

    class Meta:
        verbose_name = "Личный чат"
        verbose_name_plural = "Личные чаты"


class BaseMessage(models.Model):
    """
    Base message model

    Attributes:
        author: A ForeignKey referring to the User model.
        text: A TextField containing message text.
        is_read: A BooleanField indicating whether message is read.
        # is_deleted: A BooleanField indicating whether message is deleted.
        created_at: A DateTimeField indicating date of creation.
    """

    text = models.TextField(max_length=8192)
    is_read = models.BooleanField(default=False)
    # is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="messages")
    # reply_to = models.ForeignKey(
    #     "self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies"
    # )

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

    def __str__(self):
        return f"ProjectChatMessage<{self.pk}>"

    class Meta:
        verbose_name = "Сообщение в чате проекта"
        verbose_name_plural = "Сообщения в чатах проектов"


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

    def __str__(self):
        return f"DirectChatMessage<{self.pk}>"

    class Meta:
        verbose_name = "Сообщение в личном чате"
        verbose_name_plural = "Сообщения в личных чатах"
