from django.db import models


class BaseChat(models.Model):
    """
    Chat model

    Attributes:
        name: A CharField name of the chat.
        users: A ManyToManyField referring to the User model.
        created_at: A DateTimeField indicating date of creation.
    """

    created_at = models.DateTimeField(auto_now_add=True)

    # has to be overriden in child classes
    def get_chat_users(self):
        raise NotImplementedError

    def __str__(self):
        return f"Chat {self.pk}"

    @property
    def users_str(self):
        return ", ".join([i.email for i in self.users.all()])

    class Meta:
        verbose_name = "Чат"
        verbose_name_plural = "Чаты"
        abstract = True


class ProjectChat(BaseChat):
    """
    ProjectChat model

    Attributes:
        users: A ManyToManyField referring to the User model.
        created_at: A DateTimeField indicating date of creation.
    """

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="chats"
    )

    def get_chat_users(self):
        # TODO: return all collaborators from project + leader
        pass

    def __str__(self):
        return f"Chat {self.pk} ({self.name})"

    class Meta:
        verbose_name = "Чат проекта"
        verbose_name_plural = "Чаты проектов"


class DirectChat(BaseChat):
    """
    DirectChat model

    Attributes:
        users: A ManyToManyField referring to the User model.
        created_at: A DateTimeField indicating date of creation.
    """

    users = models.ManyToManyField("users.CustomUser", related_name="chats")

    def get_chat_users(self):
        return self.users.all()

    def __str__(self):
        return f"Direct chat {self.pk} ({self.users_str})"

    class Meta:
        verbose_name = "Личный чат"
        verbose_name_plural = "Личные чаты"


class Message(models.Model):
    """
    Message model

    Attributes:
        chat: A ForeignKey referring to the Chat model.
        author: A ForeignKey referring to the User model.
        text: A TextField containing message text.
        created_at: A DateTimeField indicating date of creation.
    """

    # TODO: add chat foreign key
    # chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        "users.CustomUser", on_delete=models.CASCADE, related_name="messages"
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Message {self.pk}"

    class Meta:
        verbose_name = "Сообщение"
        verbose_name_plural = "Сообщения"
        ordering = ["-created_at"]
