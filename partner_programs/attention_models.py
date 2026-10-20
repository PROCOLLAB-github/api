"""Личные напоминания организатора и восстанавливаемая очередь писем."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class ProgramAttentionReminderBatch(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    program = models.ForeignKey(
        "partner_programs.PartnerProgram", on_delete=models.CASCADE
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    category = models.CharField(max_length=48)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    result = models.JSONField(default=dict)


class ProgramAttentionReminder(models.Model):
    batch = models.ForeignKey(
        ProgramAttentionReminderBatch,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attention_reminders",
    )
    text = models.TextField()
    action_path = models.CharField(max_length=300)
    source_ids = models.JSONField(default=list)
    assignment_ids = models.JSONField(default=list)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    read_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)
    delivery_status = models.CharField(
        max_length=12,
        default="queued",
        choices=[(v, v) for v in ("queued", "sent", "failed", "cancelled")],
    )
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "recipient"], name="unique_attention_batch_recipient"
            )
        ]
        indexes = [
            models.Index(fields=["delivery_status", "id"]),
            models.Index(fields=["recipient", "-created_at"]),
        ]
