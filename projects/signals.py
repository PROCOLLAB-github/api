from django.db.models import Q
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

    vacancies = list(Vacancy.objects.filter(project=instance))
    target_is_active = not instance.draft
    changed_vacancies = [
        vacancy for vacancy in vacancies if vacancy.is_active != target_is_active
    ]
    now = timezone.now()

    if target_is_active:
        Vacancy.objects.filter(project=instance).filter(
            Q(is_active=False) | Q(datetime_closed__isnull=False)
        ).update(
            is_active=True,
            datetime_closed=None,
            datetime_updated=now,
        )
    else:
        Vacancy.objects.filter(project=instance).filter(
            Q(is_active=True) | Q(datetime_closed__isnull=True)
        ).update(
            is_active=False,
            datetime_closed=now,
            datetime_updated=now,
        )

    for vacancy in changed_vacancies:
        vacancy.is_active = target_is_active
        vacancy.datetime_closed = None if target_is_active else now
        if target_is_active is False:
            delete_news_for_model(vacancy)
        else:
            create_news_for_model(vacancy)
