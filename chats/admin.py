from django.contrib import admin

from chats.models import ProjectChat, DirectChat, ProjectChatMessage, DirectChatMessage


@admin.display(description="Пользователи чата")
def chat_users(obj):
    return f"{obj.get_users_str()}"


@admin.display(description="Количество сообщений")
def chat_message_count(obj):
    return obj.messages.count()


@admin.register(ProjectChat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ("id", "project", chat_users, chat_message_count, "created_at")
    list_display_links = (
        "id",
        "project",
    )


@admin.register(DirectChat)
class DirectChatAdmin(admin.ModelAdmin):
    list_display = ("id", chat_users, chat_message_count, "created_at")
    list_display_links = ("id",)


@admin.register(ProjectChatMessage)
class ProjectChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "author", "chat", "created_at")
    list_display_links = ("id", "author", "chat")


@admin.register(DirectChatMessage)
class DirectChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "author", "chat", "created_at")
    list_display_links = ("id", "author", "chat")
