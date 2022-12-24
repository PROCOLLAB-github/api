from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class BaseChat(models.Model):
    """
    Base Chat model

    Attributes:
        created_at: A DateTimeField indicating date of creation.
    """

    created_at = models.DateTimeField(auto_now_add=True)

    # has to be overriden in child classes
    def get_users(self):
        raise NotImplementedError

    def get_users_str(self):
        """returns string of users, who are in chat

        Returns:
            str: string of users, who are in chat
        """
        users = self.get_users()
        return ", ".join([user.get_full_name() for user in users])

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

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="chats"
    )

    def get_users(self):
        """
        Returns all collaborators and leader of the project.

        Returns:
            List[CustomUser]: list of users, who are collaborators or leader of the project
        """

        collaborators = self.project.collaborators.all()
        users = [collaborator.user for collaborator in collaborators]
        return users + [self.project.leader]

    def __str__(self):
        return f"ProjectChat<{self.project.id}> - {self.project.name}"

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

    users = models.ManyToManyField(User, related_name="direct_chats")

    def get_users(self):
        """
        Returns all users in chat.

        Returns:
            List[CustomUser]: list of users, who are in chat
        """

        return self.users.all()

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
        created_at: A DateTimeField indicating date of creation.
    """

    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="messages")
    text = models.TextField(max_length=8192)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Message<{self.pk}>"

    class Meta:
        verbose_name = "Сообщение"
        verbose_name_plural = "Сообщения"
        ordering = ["-created_at"]


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

    def __str__(self):
        return f"DirectChatMessage<{self.pk}>"

    class Meta:
        verbose_name = "Сообщение в личном чате"
        verbose_name_plural = "Сообщения в личных чатах"
