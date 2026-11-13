from functools import partial
from uuid import uuid4

import requests
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.views.decorators.http import require_http_methods, require_safe
from django.utils import timezone

from chats.attachments import download_chat_attachment, get_accessible_chat
from chats.direct_privacy import (
    direct_chat_opponent,
    direct_contact,
    get_incoming_policy,
    report_direct_spam,
    set_block,
    set_incoming_policy,
)
from chats.exceptions import MessageValidationException
from chats.message_context import MessageContextForm, get_message_context
from chats.models import (
    ProjectChat,
    DirectChat,
    ProjectChatMessage,
    DirectChatMessage,
    DirectChatPrivacy,
    DirectChatSpamReport,
    FileToMessage,
    ProgramChannel,
)
from chats.permissions import accessible_chats, can_publish_in_program_channel
from chats.program_channels import mark_channel_read, publish_channel_message
from chats.project_reads import mark_project_message_read, publish_project_message_read
from chats.search import ChatMessageSearchForm, search_chat_messages
from chats.services.messages import delete_message, edit_message
from chats.utils import get_user_channel_cache_key
from chats.websockets_settings import ChatType, EventGroupType, EventType
from files.models import UserFile
from files.exceptions import SelectelUploadError
from files.service import CDN, SelectelSwiftStorage, create_user_upload


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
            "<slug:object_id>" if self.model is DirectChat else "<int:object_id>"
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
                **self.extra_channel_context(request, chat),
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

    def extra_channel_context(self, request, chat):
        return {}

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
                    if not isinstance(chat, ProgramChannel):
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
                **self.extra_channel_context(request, chat),
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
                **self.extra_channel_context(request, chat),
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


class ChannelPublicationForm(forms.Form):
    text = forms.CharField(
        label="Текст публикации", required=False, strip=False, widget=forms.Textarea
    )
    files = forms.ModelMultipleChoiceField(
        label="Мои загруженные файлы", queryset=UserFile.objects.none(), required=False
    )
    client_message_id = forms.UUIDField(
        widget=forms.HiddenInput,
        error_messages={"invalid": "Некорректный номер публикации."},
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["files"].queryset = UserFile.objects.filter(user=user).order_by(
            "-datetime_uploaded"
        )


class ChannelUploadForm(forms.Form):
    file = forms.FileField(label="Файл")


@admin.register(ProgramChannel)
class ProgramChannelAdmin(ChatSearchAdmin):
    list_display = ("program", "message_search_link")
    list_display_links = None
    cdn = CDN(storage=SelectelSwiftStorage())

    def get_queryset(self, request):
        return accessible_chats(request.user, ProgramChannel).select_related("program")

    def has_view_permission(self, request, obj=None):
        if obj is None:
            return accessible_chats(request.user, ProgramChannel).exists()
        return accessible_chats(request.user, ProgramChannel).filter(pk=obj.pk).exists()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path(
                "<int:object_id>/publish/",
                self.admin_site.admin_view(
                    require_http_methods(["GET", "POST"])(self.publish_message)
                ),
                name=self.message_search_url_name + "_publish",
            ),
            path(
                "<int:object_id>/messages/<int:message_id>/read/",
                self.admin_site.admin_view(
                    require_http_methods(["POST"])(self.read_message)
                ),
                name=self.message_search_url_name + "_read",
            ),
        ] + super().get_urls()

    def extra_channel_context(self, request, chat):
        prefix = "admin:" + self.message_search_url_name
        return {
            "channel_read_route": prefix + "_read",
            "channel_publish_url": (
                reverse(prefix + "_publish", args=[chat.pk])
                if can_publish_in_program_channel(request.user, chat.program)
                else None
            ),
        }

    def change_own_message(self, request, object_id, message_id):
        chat = self.get_chat_for_member(request, object_id)
        if not can_publish_in_program_channel(request.user, chat.program):
            raise PermissionDenied("Публикации доступны менеджерам программы.")
        return super().change_own_message(request, object_id, message_id)

    def publish_message(self, request, object_id):
        chat = self.get_chat_for_member(request, object_id)
        if not can_publish_in_program_channel(request.user, chat.program):
            raise PermissionDenied("Публикации доступны менеджерам программы.")
        posted = request.method == "POST"
        uploading = posted and request.POST.get("action") == "upload"
        form = ChannelPublicationForm(
            request.user,
            request.POST if posted and not uploading else None,
            initial={"client_message_id": uuid4()},
        )
        upload_form = ChannelUploadForm(
            request.POST if uploading else None, request.FILES if uploading else None
        )
        if uploading and upload_form.is_valid():
            try:
                upload = create_user_upload(
                    self.cdn,
                    upload_form.cleaned_data["file"],
                    request.user,
                    preserve_original=True,
                )
            except (requests.RequestException, SelectelUploadError, KeyError):
                upload_form.add_error(
                    "file", "Не удалось загрузить файл. Повторите попытку."
                )
            else:
                form.initial["files"] = [upload.pk]
                self.message_user(request, "Файл загружен и выбран для публикации.")
        if posted and not uploading and form.is_valid():
            try:
                publication, _ = publish_channel_message(
                    channel_id=chat.pk,
                    author=request.user,
                    text=form.cleaned_data["text"],
                    file_urls=[file.pk for file in form.cleaned_data["files"]],
                    client_message_id=form.cleaned_data["client_message_id"],
                )
            except MessageValidationException as error:
                form.add_error(None, str(error))
            else:
                self.message_user(request, "Публикация сохранена.")
                return redirect(
                    "admin:" + self.message_search_url_name + "_context",
                    chat.pk,
                    publication["id"],
                )
        return TemplateResponse(
            request,
            "admin/chats/channel_publish.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": "Новая публикация в канале",
                "form": form,
                "upload_form": upload_form,
                "back_url": reverse(
                    "admin:" + self.message_search_url_name, args=[chat.pk]
                ),
            },
            status=400 if form.errors or upload_form.errors else 200,
        )

    def read_message(self, request, object_id, message_id):
        chat = self.get_chat_for_member(request, object_id)
        try:
            mark_channel_read(
                channel_id=chat.pk, user=request.user, message_id=message_id
            )
        except MessageValidationException as error:
            raise Http404(str(error)) from error
        self.message_user(request, "Публикации отмечены прочитанными.")
        return redirect(
            "admin:" + self.message_search_url_name + "_context", chat.pk, message_id
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
    change_list_template = "admin/chats/direct_chat_list.html"

    def has_module_permission(self, request):
        return request.user.is_staff

    def get_queryset(self, request):
        if request.user.is_superuser:
            return super().get_queryset(request)
        return accessible_chats(request.user, DirectChat)

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return super().has_view_permission(request, obj)
        return (
            obj is None
            or accessible_chats(request.user, DirectChat).filter(pk=obj.pk).exists()
        )

    def has_add_permission(self, request):
        return request.user.is_superuser and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_delete_permission(request, obj)

    def get_urls(self):
        return [
            path(
                "incoming-settings/",
                self.admin_site.admin_view(
                    require_http_methods(["GET", "POST"])(self.incoming_settings)
                ),
                name="chats_directchat_incoming_settings",
            ),
            path(
                "<slug:object_id>/privacy/",
                self.admin_site.admin_view(
                    require_http_methods(["GET", "POST"])(self.chat_privacy)
                ),
                name=self.message_search_url_name + "_privacy",
            ),
        ] + super().get_urls()

    def incoming_settings(self, request):
        form = DirectPrivacyForm(
            request.POST if request.method == "POST" else None,
            initial={"incoming": get_incoming_policy(request.user)},
        )
        if request.method == "POST" and form.is_valid():
            set_incoming_policy(request.user, form.cleaned_data["incoming"])
            self.message_user(request, "Настройки сохранены.")
            return redirect("admin:chats_directchat_incoming_settings")
        return TemplateResponse(
            request,
            "admin/chats/direct_privacy.html",
            {
                **self.admin_site.each_context(request),
                "title": "Настройки личных сообщений",
                "opts": self.model._meta,
                "form": form,
                "search_url": reverse("admin:chats_directchat_changelist"),
                "back_label": "К личным чатам",
            },
            status=400 if form.errors else 200,
        )

    def extra_channel_context(self, request, chat):
        return {
            "direct_privacy_url": reverse(
                "admin:" + self.message_search_url_name + "_privacy", args=[chat.pk]
            )
        }

    def chat_privacy(self, request, object_id):
        chat = self.get_chat_for_member(request, object_id)
        posted = request.method == "POST"
        action = request.POST.get("action")
        try:
            other = direct_chat_opponent(chat, request.user)
        except MessageValidationException:
            other = None
        error = None
        if posted:
            try:
                if action in ("block", "unblock") and other is not None:
                    set_block(request.user, other, action == "block")
                elif action == "report" and other is not None:
                    report = DirectSpamReportForm(request.POST)
                    if not report.is_valid():
                        raise MessageValidationException("Некорректный номер сообщения.")
                    report_direct_spam(
                        chat, request.user, report.cleaned_data["message_id"]
                    )
                else:
                    raise MessageValidationException("Действие недоступно.")
            except MessageValidationException as exc:
                error = str(exc)
            if not error:
                self.message_user(
                    request,
                    (
                        "Жалоба отправлена."
                        if action == "report"
                        else "Настройки сохранены."
                    ),
                )
                return redirect(
                    "admin:" + self.message_search_url_name + "_privacy", chat.pk
                )
        return TemplateResponse(
            request,
            "admin/chats/direct_privacy.html",
            {
                **self.admin_site.each_context(request),
                "title": "Настройки личных сообщений",
                "opts": self.model._meta,
                "settings_url": reverse("admin:chats_directchat_incoming_settings"),
                "contact": direct_contact(request.user, other, chat) if other else None,
                "error": error,
                "search_url": reverse(
                    "admin:" + self.message_search_url_name, args=[chat.pk]
                ),
            },
            status=400 if error else 200,
        )


class DirectPrivacyForm(forms.Form):
    incoming = forms.ChoiceField(
        label="Кто может начать диалог со мной",
        choices=DirectChatPrivacy.Incoming.choices,
        error_messages={
            "invalid_choice": "Выберите, кто может начать диалог.",
            "required": "Выберите, кто может начать диалог.",
        },
    )


class DirectSpamReportForm(forms.Form):
    message_id = forms.IntegerField(required=False, min_value=1, max_value=2**63 - 1)


@admin.register(DirectChatSpamReport)
class DirectChatSpamReportAdmin(admin.ModelAdmin):
    list_display = (
        "message_id",
        "reporter",
        "reported_user",
        "created_at",
        "reviewed_at",
    )
    list_filter = ("reviewed_at",)
    fields = (
        "chat",
        "reporter",
        "reported_user",
        "message_id",
        "message_text",
        "created_at",
        "reviewed_at",
    )
    readonly_fields = fields
    actions = ("mark_reviewed",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(permissions=["change"], description="Отметить рассмотренными")
    def mark_reviewed(self, request, queryset):
        count = queryset.filter(reviewed_at__isnull=True).update(
            reviewed_at=timezone.now()
        )
        self.message_user(request, f"Отмечено рассмотренными: {count}")


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
