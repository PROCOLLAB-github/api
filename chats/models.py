from django.db import models


class Chat(models.Model):
    """
    Chat model

    Attributes:
        name: A CharField name of the chat.
        users: A ManyToManyField referring to the User model.
    """

    users = models.ManyToManyField("users.CustomUser", related_name="chats")
    name = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.name or f"Chat {self.pk}"

    class Meta:
        verbose_name = "Чат"
        verbose_name_plural = "Чаты"


class Message(models.Model):
    """
    Message model

    Attributes:
        chat: A ForeignKey referring to the Chat model.
        author: A ForeignKey referring to the User model.
        text: A TextField containing message text.
        created_at: A DateTimeField indicating date of creation.

    """

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
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
