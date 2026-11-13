from functools import partial

from asgiref.sync import async_to_sync
from django.contrib import admin, messages
from django.db import transaction

from chats.exceptions import MessageValidationException
from chats.models import (
    ProjectChat,
    DirectChat,
    ProjectChatMessage,
    DirectChatMessage,
    FileToMessage,
)
from chats.project_reads import mark_project_message_read, publish_project_message_read


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
    exclude = ("is_read",)
    actions = ("mark_read_for_me",)

    @admin.action(permissions=["view"], description="Отметить как прочитанные для себя")
    def mark_read_for_me(self, request, queryset):
        try:
            with transaction.atomic():
                marked = 0
                for chat_id, message_id in queryset.order_by("pk").values_list(
                    "chat_id", "pk"
                ):
                    author_id, read_count, created = mark_project_message_read(
                        chat_id=chat_id, message_id=message_id, user=request.user
                    )
                    if created:
                        marked += 1
                        transaction.on_commit(
                            partial(
                                async_to_sync(publish_project_message_read),
                                chat_id=chat_id,
                                message_id=message_id,
                                user_id=request.user.pk,
                                author_id=author_id,
                                read_count=read_count,
                            ),
                            robust=True,
                        )
        except MessageValidationException as error:
            self.message_user(request, str(error), level=messages.ERROR)
        else:
            self.message_user(
                request, f"Отмечено прочитанными: {marked}", level=messages.SUCCESS
            )


@admin.register(DirectChatMessage)
class DirectChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "author", "chat", "created_at")
    list_display_links = ("id", "author", "chat")


@admin.register(FileToMessage)
class FileToMessageAdmin(admin.ModelAdmin):
    list_display = (
        "file",
        "direct_message",
        "project_message",
    )
    list_display_links = (
        "file",
        "direct_message",
        "project_message",
    )
