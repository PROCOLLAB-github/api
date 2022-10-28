from django.contrib import admin

from chats.models import Chat, Message


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ("name", "users_str", "created_at")
    list_display_links = ("name",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "chat", "author", "text", "created_at")
    list_display_links = ("id",)
