from functools import partial

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.views.decorators.http import require_http_methods, require_safe

from chats.attachments import download_chat_attachment, get_accessible_chat
from chats.exceptions import MessageValidationException
from chats.message_context import MessageContextForm, get_message_context
from chats.models import (
    ProjectChat,
    DirectChat,
    ProjectChatMessage,
    DirectChatMessage,
    FileToMessage,
)
from chats.permissions import accessible_chats
from chats.project_reads import mark_project_message_read, publish_project_message_read
from chats.search import ChatMessageSearchForm, search_chat_messages
from chats.services.messages import delete_message, edit_message
from chats.utils import get_user_channel_cache_key
from chats.websockets_settings import ChatType, EventGroupType, EventType


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
        object_path = (
            "<int:object_id>" if self.model is ProjectChat else "<slug:object_id>"
        )
        return [
            path(
                object_path + "/message-search/",
                self.admin_site.admin_view(self.message_search),
                name=self.message_search_url_name,
            ),
            path(
                object_path + "/messages/<int:message_id>/context/",
                self.admin_site.admin_view(require_safe(self.message_context)),
                name=self.message_search_url_name + "_context",
            ),
            path(
                object_path + "/messages/<int:message_id>/change/",
                self.admin_site.admin_view(
                    require_http_methods(["GET", "POST"])(self.change_own_message)
                ),
                name=self.message_search_url_name + "_change",
            ),
            path(
                object_path
                + "/messages/<int:message_id>/files/<slug:attachment_id>/download/",
                self.admin_site.admin_view(require_safe(self.attachment_download)),
                name=self.message_search_url_name + "_download",
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
        chat = self.get_chat_for_member(request, object_id)
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
                "chat": chat,
                "message_context_route": "admin:"
                + self.message_search_url_name
                + "_context",
                "message_change_route": "admin:"
                + self.message_search_url_name
                + "_change",
                "attachment_download_route": "admin:"
                + self.message_search_url_name
                + "_download",
            },
        )

    def get_chat_for_member(self, request, object_id):
        chat = get_accessible_chat(request.user, self.model, object_id)
        if not self.has_view_or_change_permission(request, chat):
            raise PermissionDenied
        return chat

    def attachment_download(self, request, object_id, message_id, attachment_id):
        chat = self.get_chat_for_member(request, object_id)
        return download_chat_attachment(request, chat, message_id, attachment_id)

    def change_own_message(self, request, object_id, message_id):
        chat = self.get_chat_for_member(request, object_id)
        message = get_object_or_404(
            chat.messages, pk=message_id, author=request.user, is_deleted=False
        )
        form = OwnMessageForm(
            request.POST if request.method == "POST" else None,
            initial={"text": message.text},
        )
        search_route = "admin:" + self.message_search_url_name
        if request.method == "POST" and form.is_valid():
            change = dict(
                chat_model=self.model,
                chat_id=chat.pk,
                message_id=message.pk,
                author=request.user,
            )
            try:
                with transaction.atomic():
                    if form.cleaned_data["action"] == "delete":
                        delete_message(**change)
                        event_type = EventType.DELETE_MESSAGE
                        content = {"message_id": message.pk}
                    else:
                        event_type = EventType.EDIT_MESSAGE
                        content = {
                            "message": edit_message(
                                **change, text=form.cleaned_data["text"]
                            )
                        }
                    transaction.on_commit(
                        partial(self.publish_change, chat, event_type, content),
                        robust=True,
                    )
            except MessageValidationException as error:
                form.add_error(None, str(error))
            else:
                if event_type == EventType.DELETE_MESSAGE:
                    self.message_user(request, "Сообщение удалено.")
                    return redirect(search_route, chat.pk)
                self.message_user(request, "Сообщение сохранено.")
                return redirect(search_route + "_context", chat.pk, message.pk)
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            "admin/chats/message_change.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": "Изменение сообщения",
                "chat": chat,
                "message": message,
                "form": form,
                "message_context_route": search_route + "_context",
            },
            status=400 if form.errors else 200,
        )

    def publish_change(self, chat, event_type, content):
        layer = get_channel_layer()
        if layer is None:
            return
        if isinstance(chat, ProjectChat):
            async_to_sync(layer.group_send)(
                f"{EventGroupType.CHATS_RELATED}_{chat.pk}",
                {
                    "type": event_type,
                    "content": {
                        "chat_id": chat.pk,
                        "chat_type": ChatType.PROJECT,
                        **content,
                    },
                    "_project_chat_id": chat.pk,
                },
            )
        else:
            event = {
                "type": event_type,
                "content": {"chat_id": chat.pk, "chat_type": ChatType.DIRECT, **content},
                "_direct_chat_id": chat.pk,
            }
            for user in chat.users.all():
                channel = cache.get(get_user_channel_cache_key(user))
                if channel:
                    async_to_sync(layer.send)(channel, event)

    def message_context(self, request, object_id, message_id):
        chat = self.get_chat_for_member(request, object_id)
        form = MessageContextForm(request.GET)
        context = None
        if form.is_valid():
            queryset = chat.messages.select_related("author").prefetch_related(
                "file_to_message__file"
            )
            context = get_message_context(chat, queryset, message_id, **form.cleaned_data)
        request.current_app = self.admin_site.name
        search_route = "admin:" + self.message_search_url_name
        return TemplateResponse(
            request,
            "admin/chats/message_context.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": "Сообщение в переписке",
                "chat": chat,
                "context_form": form,
                "context": context,
                "anchor_id": (
                    message_id
                    if context and form.cleaned_data["direction"] == "around"
                    else None
                ),
                "search_route": search_route,
                "message_context_route": search_route + "_context",
                "message_change_route": search_route + "_change",
                "attachment_download_route": search_route + "_download",
            },
            status=200 if context is not None else 400,
        )


class OwnMessageForm(forms.Form):
    text = forms.CharField(
        label="Текст сообщения", required=False, strip=False, widget=forms.Textarea
    )
    action = forms.ChoiceField(
        choices=[("edit", "Сохранить"), ("delete", "Удалить")],
        widget=forms.HiddenInput,
        error_messages={
            "required": "Выберите действие.",
            "invalid_choice": "Выберите доступное действие.",
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


class ChatMessageAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        chat_model = self.model._meta.get_field("chat").related_model
        return queryset.filter(
            chat_id__in=accessible_chats(request.user, chat_model).values("pk")
        )

    def has_add_permission(self, request):
        return request.user.is_superuser and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_delete_permission(request, obj)


@admin.register(ProjectChatMessage)
class ProjectChatMessageAdmin(ChatMessageAdmin):
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
class DirectChatMessageAdmin(ChatMessageAdmin):
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
