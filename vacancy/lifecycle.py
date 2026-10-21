"""Архив вакансий: сохранение истории и единый порядок блокировок."""

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied

from projects.models import Project
from vacancy.mapping import MessageTypeEnum
from vacancy.models import Vacancy, VacancyResponse
from vacancy.response_services import _email_payload
from vacancy.selectors import can_manage_vacancy
from vacancy.tasks import send_email
from django.db import transaction


def lock_managed_vacancy(vacancy_id, actor):
    """Вызывать внутри atomic; порядок Project → Vacancy как у откликов."""
    try:
        project_id = Vacancy.objects.only("project_id").get(pk=vacancy_id).project_id
        project = Project.objects.select_for_update().get(pk=project_id)
        vacancy = Vacancy.objects.select_for_update().get(pk=vacancy_id)
    except (Vacancy.DoesNotExist, Project.DoesNotExist) as error:
        raise NotFound() from error
    vacancy.project = project
    if not can_manage_vacancy(actor, vacancy):
        raise PermissionDenied()
    return vacancy


def validate_reopening(vacancy, is_active):
    if (
        is_active
        and not vacancy.is_active
        and (vacancy.project.draft or not vacancy.project.is_public)
    ):
        raise serializers.ValidationError(
            {
                "is_active": "Возобновить набор можно только в опубликованном публичном проекте."
            }
        )


def resolve_pending_responses(vacancy):
    """Вызывать после закрытия под блокировкой вакансии; решения не переписываются."""
    pending = list(
        VacancyResponse.objects.select_for_update().filter(
            vacancy=vacancy, is_approved__isnull=True
        )
    )
    VacancyResponse.objects.filter(pk__in=[response.pk for response in pending]).update(
        is_approved=False, datetime_updated=timezone.now()
    )
    for response in pending:
        response.vacancy = vacancy
        payload = _email_payload(response, MessageTypeEnum.REJECTED.value)
        transaction.on_commit(lambda payload=payload: send_email.delay(payload))


def ensure_no_responses(vacancy):
    if VacancyResponse.objects.filter(vacancy=vacancy).exists():
        raise serializers.ValidationError(
            {
                "code": "vacancy_has_responses",
                "detail": "Вакансию с откликами нельзя удалить. История кандидатов должна сохраниться.",
            }
        )
