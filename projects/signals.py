from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from chats.models import ProjectChat
from feed.services import delete_news_for_model, create_news_for_model
from projects.models import Collaborator, Project
from vacancy.models import Vacancy


@receiver(pre_save, sender=Project)
def remember_project_draft_state(
    sender, instance, raw=False, update_fields=None, **kwargs
):
    """Сохраняет предыдущее состояние draft для обработки реального перехода."""

    if raw or instance._state.adding:
        instance._previous_draft = None
        return
    if update_fields is not None and "draft" not in update_fields:
        instance._previous_draft = instance.draft
        return
    instance._previous_draft = (
        sender.objects.filter(pk=instance.pk).values_list("draft", flat=True).first()
    )


@receiver(post_save, sender=Project)
def create_project(sender, instance, created, **kwargs):
    """
    Creates collaborator for the project leader and ProjectChat on project creation
    """

    if not instance.draft:
        ProjectChat.objects.get_or_create(project=instance)

    if created:
        Collaborator.objects.create(
            user=instance.leader, project=instance, role="Основатель"
        )


@receiver(post_save, sender=Project)
def update_vacancy(sender, instance, created, raw=False, **kwargs):
    previous_draft = getattr(instance, "_previous_draft", None)
    if raw or created or previous_draft is None or previous_draft == instance.draft:
        return

    target_is_active = not instance.draft
    # Only vacancies suspended by the project lifecycle can resume automatically.
    # Inactive legacy rows and explicitly archived vacancies keep their history.
    queryset = Vacancy.objects.filter(project=instance)
    if target_is_active:
        queryset = queryset.filter(is_active=False, resume_on_publish=True)
    else:
        queryset = queryset.filter(is_active=True)
    changed_vacancies = list(queryset)
    now = timezone.now()

    queryset.update(
        is_active=target_is_active,
        resume_on_publish=not target_is_active,
        datetime_closed=None if target_is_active else now,
        datetime_updated=now,
    )

    for vacancy in changed_vacancies:
        vacancy.is_active = target_is_active
        vacancy.datetime_closed = None if target_is_active else now
        if target_is_active is False:
            delete_news_for_model(vacancy)
        else:
            create_news_for_model(vacancy)
