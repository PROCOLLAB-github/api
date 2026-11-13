from functools import partial

from asgiref.sync import async_to_sync
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from chats.exceptions import MessageValidationException
from chats.models import (
    ProjectChat,
    DirectChat,
    ProjectChatMessage,
    DirectChatMessage,
    FileToMessage,
)
from chats.project_reads import mark_project_message_read, publish_project_message_read
from chats.search import ChatMessageSearchForm, accessible_chats, search_chat_messages


@admin.display(description="Пользователи чата")
def chat_users(obj):
    return f"{obj.get_users_str()}"


@admin.display(description="Количество сообщений")
def chat_message_count(obj):
    return obj.messages.count()


class ChatSearchAdmin(admin.ModelAdmin):
    @property
    def message_search_url_name(self):
        return (
            f"{self.model._meta.app_label}_{self.model._meta.model_name}_message_search"
        )

    def get_urls(self):
        converter = "int" if self.model is ProjectChat else "slug"
        return [
            path(
                "<" + converter + ":object_id>/message-search/",
                self.admin_site.admin_view(self.message_search),
                name=self.message_search_url_name,
            ),
        ] + super().get_urls()

    @admin.display(description="Поиск по переписке")
    def message_search_link(self, chat):
        url = reverse(
            "admin:" + self.message_search_url_name,
            args=[chat.pk],
            current_app=self.admin_site.name,
        )
        return format_html('<a href="{}">Найти в чате</a>', url)

    def message_search(self, request, object_id):
        visible = accessible_chats(request.user, self.model)
        chat = get_object_or_404(visible, pk=object_id)
        if not self.has_view_or_change_permission(request, chat):
            raise PermissionDenied
        form = ChatMessageSearchForm(request.GET)
        page = None
        if form.is_valid():
            matches = (
                search_chat_messages(chat, form.cleaned_data)
                .select_related("author")
                .prefetch_related("file_to_message__file")
            )
            page = Paginator(matches, 20).get_page(request.GET.get("page"))
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            "admin/chats/message_search.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": "Поиск по переписке",
                "form": form,
                "page": page,
            },
        )


@admin.register(ProjectChat)
class ChatAdmin(ChatSearchAdmin):
    list_display = (
        "id",
        "project",
        chat_users,
        chat_message_count,
        "created_at",
        "message_search_link",
    )
    list_display_links = (
        "id",
        "project",
    )


@admin.register(DirectChat)
class DirectChatAdmin(ChatSearchAdmin):
    list_display = (
        "id",
        chat_users,
        chat_message_count,
        "created_at",
        "message_search_link",
    )
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
