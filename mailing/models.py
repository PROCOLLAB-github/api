import os
import uuid

from django.conf import settings
from django.db import models
from .constants import get_default_mailing_schema


def get_template_path(instance, filename):
    ext = filename.split(".")[-1]
    filename = "%s.%s" % (uuid.uuid4(), ext)
    return os.path.join("templates/mailing/emails", filename)


class MailingSchema(models.Model):
    name = models.CharField(max_length=100, unique=True)
    schema = models.JSONField(default=get_default_mailing_schema, null=True, blank=True)
    template = models.TextField()

    class Meta:
        verbose_name = "Схема шаблона письма"
        verbose_name_plural = "Схемы шаблонов писем"

    def __str__(self):
        return f"MailingSchema<{self.name}>"


class MailingScenarioLog(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    scenario_code = models.CharField(max_length=128)
    program = models.ForeignKey(
        "partner_programs.PartnerProgram",
        on_delete=models.CASCADE,
        related_name="mailing_scenario_logs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mailing_scenario_logs",
    )
    scheduled_for = models.DateField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    datetime_created = models.DateTimeField(auto_now_add=True)
    datetime_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Лог сценария рассылки"
        verbose_name_plural = "Логи сценариев рассылки"
        unique_together = ("scenario_code", "program", "user", "scheduled_for")
        indexes = [
            models.Index(fields=["scenario_code", "scheduled_for"]),
            models.Index(fields=["program", "scheduled_for"]),
            models.Index(fields=["user", "scheduled_for"]),
        ]

    def __str__(self):
        return (
            f"MailingScenarioLog<{self.scenario_code}> "
            f"program={self.program_id} user={self.user_id} "
            f"date={self.scheduled_for} status={self.status}"
        )
