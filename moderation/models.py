from django.conf import settings
from django.db import models


class ModerationLog(models.Model):
    ACTION_SUBMIT_TO_MODERATION = "submit_to_moderation"
    ACTION_SUBMITTED_LEGACY = "submitted"
    ACTION_SUBMITTED = ACTION_SUBMIT_TO_MODERATION
    ACTION_APPROVE = "approve"
    ACTION_APPROVED_LEGACY = "approved"
    ACTION_APPROVED = ACTION_APPROVE
    ACTION_REJECT = "reject"
    ACTION_REJECTED_LEGACY = "rejected"
    ACTION_REJECTED = ACTION_REJECT
    ACTION_WITHDRAW = "withdraw"
    ACTION_WITHDRAWN_LEGACY = "withdrawn"
    ACTION_WITHDRAWN = ACTION_WITHDRAW
    ACTION_AUTO_FREEZE = "auto_freeze"
    ACTION_FREEZE = "freeze"
    ACTION_RESTORE = "restore"
    ACTION_ARCHIVE = "archive"
    ACTION_COMPLETE = "complete"
    ACTION_VERIFICATION_SUBMITTED = "verification_submitted"
    ACTION_VERIFICATION_APPROVE = "verification_approve"
    ACTION_VERIFICATION_REJECT = "verification_reject"
    ACTION_VERIFICATION_REVOKE = "verification_revoke"
    ACTION_AUTO_FROZEN = ACTION_AUTO_FREEZE
    ACTION_UNFROZEN = ACTION_RESTORE
    ACTION_ARCHIVED = ACTION_ARCHIVE
    ACTION_VERIFICATION_APPROVED = ACTION_VERIFICATION_APPROVE
    ACTION_VERIFICATION_REJECTED = ACTION_VERIFICATION_REJECT
    ACTION_VERIFICATION_REVOKED = ACTION_VERIFICATION_REVOKE

    SUBMISSION_ACTIONS = (ACTION_SUBMIT_TO_MODERATION, ACTION_SUBMITTED_LEGACY)
    DECISION_ACTIONS = (
        ACTION_APPROVE,
        ACTION_APPROVED_LEGACY,
        ACTION_REJECT,
        ACTION_REJECTED_LEGACY,
    )
    REJECT_ACTIONS = (ACTION_REJECT, ACTION_REJECTED_LEGACY)

    ACTION_CHOICES = [
        (ACTION_SUBMIT_TO_MODERATION, "Отправка на модерацию"),
        (ACTION_SUBMITTED_LEGACY, "Отправка на модерацию"),
        (ACTION_APPROVE, "Одобрение"),
        (ACTION_APPROVED_LEGACY, "Одобрение"),
        (ACTION_REJECT, "Отклонение"),
        (ACTION_REJECTED_LEGACY, "Отклонение"),
        (ACTION_WITHDRAW, "Отзыв с модерации"),
        (ACTION_WITHDRAWN_LEGACY, "Отзыв с модерации"),
        (ACTION_AUTO_FREEZE, "Автоматическая заморозка"),
        (ACTION_FREEZE, "Ручная заморозка"),
        (ACTION_RESTORE, "Восстановление"),
        (ACTION_ARCHIVE, "Архивация"),
        (ACTION_COMPLETE, "Завершение"),
        (ACTION_VERIFICATION_SUBMITTED, "Заявка на верификацию"),
        (ACTION_VERIFICATION_APPROVE, "Верификация одобрена"),
        (ACTION_VERIFICATION_REJECT, "Верификация отклонена"),
        (ACTION_VERIFICATION_REVOKE, "Верификация отозвана"),
    ]

    REJECTION_REASON_INSUFFICIENT_DATA = "insufficient_data"
    REJECTION_REASON_PLATFORM_RULES = "platform_rules"
    REJECTION_REASON_DUPLICATE = "duplicate"
    REJECTION_REASON_INAPPROPRIATE_CONTENT = "inappropriate_content"
    REJECTION_REASON_SUSPICIOUS_ORGANIZER = "suspicious_organizer"
    REJECTION_REASON_OTHER = "other"

    REJECTION_REASON_CHOICES = [
        (REJECTION_REASON_INSUFFICIENT_DATA, "Недостаточно данных"),
        (REJECTION_REASON_PLATFORM_RULES, "Нарушение правил платформы"),
        (REJECTION_REASON_DUPLICATE, "Дублирующий чемпионат"),
        (REJECTION_REASON_INAPPROPRIATE_CONTENT, "Некорректное содержание"),
        (REJECTION_REASON_SUSPICIOUS_ORGANIZER, "Подозрительный организатор"),
        (REJECTION_REASON_OTHER, "Другая причина"),
    ]

    program = models.ForeignKey(
        "partner_programs.PartnerProgram",
        on_delete=models.CASCADE,
        related_name="moderation_logs",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderation_logs",
    )
    action = models.CharField(
        max_length=40,
        choices=ACTION_CHOICES,
        db_index=True,
    )
    status_before = models.CharField(max_length=20, blank=True)
    status_after = models.CharField(max_length=20, blank=True)
    comment = models.TextField(blank=True)
    rejection_reason = models.CharField(
        max_length=40,
        choices=REJECTION_REASON_CHOICES,
        blank=True,
    )
    sections_to_fix = models.JSONField(default=list, blank=True)
    datetime_created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Moderation log"
        verbose_name_plural = "Moderation logs"
        ordering = ["-datetime_created", "-id"]
        indexes = [
            models.Index(fields=["program", "action", "-datetime_created"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} - {self.program_id}"
