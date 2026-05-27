from django.contrib import admin

from notifications.models import (
    Notification,
    NotificationChannelPreference,
    NotificationDelivery,
    TelegramAccount,
    TelegramLinkToken,
)


class NotificationDeliveryInline(admin.TabularInline):
    model = NotificationDelivery
    extra = 0
    readonly_fields = (
        "channel",
        "status",
        "attempts",
        "provider_message_id",
        "sent_at",
        "error",
        "last_error",
    )
    can_delete = False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "type", "title", "is_read", "created_at")
    list_filter = ("type", "is_read", "created_at")
    search_fields = ("recipient__email", "title", "message", "dedupe_key")
    readonly_fields = ("created_at", "dedupe_key")
    inlines = [NotificationDeliveryInline]


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "notification",
        "channel",
        "status",
        "attempts",
        "sent_at",
    )
    list_filter = ("channel", "status")
    search_fields = (
        "notification__recipient__email",
        "notification__title",
        "error",
        "last_error",
        "provider_message_id",
    )


@admin.register(TelegramAccount)
class TelegramAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "telegram_chat_id", "telegram_username", "is_active")
    list_filter = ("is_active",)
    search_fields = ("user__email", "telegram_username", "telegram_chat_id")
    readonly_fields = ("linked_at", "datetime_created", "datetime_updated")


@admin.register(TelegramLinkToken)
class TelegramLinkTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "expires_at", "used_at", "created_at")
    list_filter = ("used_at", "expires_at")
    search_fields = ("user__email", "token_hash")
    readonly_fields = ("token_hash", "created_at")


@admin.register(NotificationChannelPreference)
class NotificationChannelPreferenceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "channel", "event_type", "enabled")
    list_filter = ("channel", "event_type", "enabled")
    search_fields = ("user__email",)
