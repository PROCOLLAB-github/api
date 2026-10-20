"""Versioned participant questionnaire, separate from project fields and education."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ProgramRegistration(models.Model):
    program = models.OneToOneField(
        "partner_programs.PartnerProgram",
        on_delete=models.CASCADE,
        related_name="registration_config",
    )
    draft = models.JSONField(default=dict)
    published = models.JSONField(null=True, blank=True, editable=False)
    revision = models.PositiveIntegerField(default=0, editable=False)
    published_version = models.PositiveIntegerField(default=0, editable=False)
    published_at = models.DateTimeField(null=True, editable=False)
    external_status = models.CharField(
        max_length=20,
        default="not_connected",
        choices=[(v, v) for v in ("not_connected", "requested", "connected")],
    )
    external_url = models.URLField(blank=True)
    connection_website_url = models.URLField("Сайт мероприятия", blank=True)
    connection_comment = models.TextField(blank=True)
    connection_contact = models.CharField(
        "Контакт для связи", max_length=500, blank=True
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    requested_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        super().clean()
        if self.external_status == "connected" and not self.external_url:
            raise ValidationError({"external_url": "Укажите адрес подключённой формы."})

    def __str__(self):
        return f"Регистрация программы {self.program_id}"


class PendingProgramRegistration(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program = models.ForeignKey(
        "partner_programs.PartnerProgram", on_delete=models.CASCADE
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    answers = models.JSONField(default=dict)
    schema = models.JSONField(default=dict)
    generation = models.PositiveIntegerField(default=1)
    confirmed_at = models.DateTimeField(null=True, editable=False)
    last_sent_at = models.DateTimeField(auto_now_add=True)
    delivery_status = models.CharField(max_length=12, default="queued")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["program", "user"], name="unique_pending_program_registration"
            )
        ]
