from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Type(models.TextChoices):
        PROJECT_INVITE_CREATED = "project_invite_created", "Приглашение в проект"
        PROJECT_INVITE_ACCEPTED = (
            "project_invite_accepted",
            "Приглашение в проект принято",
        )
        PROJECT_INVITE_DECLINED = (
            "project_invite_declined",
            "Приглашение в проект отклонено",
        )
        PROJECT_INVITE_REVOKED = "project_invite_revoked", "Приглашение в проект отозвано"
        VACANCY_RESPONSE_CREATED = "vacancy_response_created", "Новый отклик на вакансию"
        VACANCY_RESPONSE_ACCEPTED = "vacancy_response_accepted", "Отклик принят"
        VACANCY_RESPONSE_DECLINED = "vacancy_response_declined", "Отклик отклонён"
        TEAM_INVITE_CREATED = "team_invite_created", "Приглашение в команду"
        TEAM_INVITE_ACCEPTED = "team_invite_accepted", "Приглашение в команду принято"
        TEAM_INVITE_DECLINED = "team_invite_declined", "Приглашение в команду отклонено"
        TEAM_INVITE_REVOKED = "team_invite_revoked", "Приглашение в команду отозвано"
        APPLICATION_SUBMITTED = "application_submitted", "Заявка отправлена"
        APPLICATION_STATUS_CHANGED = "application_status_changed", "Статус заявки изменён"
        SUBMISSION_SUBMITTED = "submission_submitted", "Решение отправлено"
        SUBMISSION_STATUS_CHANGED = "submission_status_changed", "Статус решения изменён"
        EXPERT_ASSIGNMENT_CREATED = "expert_assignment_created", "Назначена экспертиза"
        EXPERT_ASSIGNMENT_REVOKED = "expert_assignment_revoked", "Экспертиза отозвана"
        EVALUATION_SUBMITTED = "evaluation_submitted", "Оценка отправлена"
        NEWS_COMMENT_CREATED = "news_comment_created", "Новый комментарий"

    class Category(models.TextChoices):
        PROJECT = "project", "Проекты"
        VACANCY = "vacancy", "Вакансии"
        PROGRAM = "program", "Программы"
        EXPERT = "expert", "Экспертиза"
        NEWS = "news", "Новости"
        SYSTEM = "system", "Система"

    TYPE_CATEGORY = {
        Type.PROJECT_INVITE_CREATED: Category.PROJECT,
        Type.PROJECT_INVITE_ACCEPTED: Category.PROJECT,
        Type.PROJECT_INVITE_DECLINED: Category.PROJECT,
        Type.PROJECT_INVITE_REVOKED: Category.PROJECT,
        Type.VACANCY_RESPONSE_CREATED: Category.VACANCY,
        Type.VACANCY_RESPONSE_ACCEPTED: Category.VACANCY,
        Type.VACANCY_RESPONSE_DECLINED: Category.VACANCY,
        Type.TEAM_INVITE_CREATED: Category.PROGRAM,
        Type.TEAM_INVITE_ACCEPTED: Category.PROGRAM,
        Type.TEAM_INVITE_DECLINED: Category.PROGRAM,
        Type.TEAM_INVITE_REVOKED: Category.PROGRAM,
        Type.APPLICATION_SUBMITTED: Category.PROGRAM,
        Type.APPLICATION_STATUS_CHANGED: Category.PROGRAM,
        Type.SUBMISSION_SUBMITTED: Category.PROGRAM,
        Type.SUBMISSION_STATUS_CHANGED: Category.PROGRAM,
        Type.EXPERT_ASSIGNMENT_CREATED: Category.EXPERT,
        Type.EXPERT_ASSIGNMENT_REVOKED: Category.EXPERT,
        Type.EVALUATION_SUBMITTED: Category.EXPERT,
        Type.NEWS_COMMENT_CREATED: Category.NEWS,
    }

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_notifications",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="acted_notifications",
        null=True,
        blank=True,
    )
    type = models.CharField(max_length=64, choices=Type.choices)
    category = models.CharField(max_length=16, choices=Category.choices)
    title = models.CharField(max_length=160)
    message = models.TextField()
    action_url = models.CharField(max_length=500, null=True, blank=True)
    event_key = models.CharField(max_length=255)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "event_key"],
                name="uniq_notification_recipient_event",
            )
        ]
        indexes = [
            models.Index(
                fields=["recipient", "-created_at"],
                name="notif_rec_created_idx",
            ),
            models.Index(
                fields=["recipient", "read_at", "-created_at"],
                name="notif_rec_read_created_idx",
            ),
        ]

    def __str__(self):
        return f"Notification<{self.pk}> recipient={self.recipient_id} type={self.type}"
