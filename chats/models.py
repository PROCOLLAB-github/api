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

    def __str__(self):
        return f"BaseChat {self.pk}"

    class Meta:
        abstract = True


class ProjectChat(BaseChat):
    """
    ProjectChat model

    Attributes:
        created_at: A DateTimeField indicating date of creation.
    """

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="chats"
    )

    def get_users(self):
        # TODO: return all collaborators from project + leader
        pass

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
    """
    first_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="direct_chats")
    second_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="direct_chats")

    def get_users(self):
        return [self.first_user, self.second_user]

    def __str__(self):
        return f"DirectChat<{self.first_user.id}-{self.second_user.id}> -" \
               f" {self.first_user.first_name} {self.first_user.last_name} -" \
               f" {self.second_user.first_name} {self.second_user.last_name}"

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
