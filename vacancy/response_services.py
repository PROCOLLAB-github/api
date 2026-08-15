from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied

from projects.models import Collaborator
from notifications.events import (
    notify_vacancy_response_created,
    notify_vacancy_response_resolved,
)
from vacancy.mapping import CeleryEmailParams, MessageTypeEnum
from vacancy.models import Vacancy, VacancyResponse
from vacancy.tasks import send_email


def _ensure_can_manage(vacancy: Vacancy, user) -> None:
    """Повторно проверяет право внутри транзакции после блокировки вакансии."""

    if not (
        vacancy.project.leader_id == user.id
        or getattr(user, "is_staff", False)
        or getattr(user, "is_superuser", False)
    ):
        raise PermissionDenied()


def _lock_vacancy_then_response(
    response_id: int,
) -> tuple[Vacancy, VacancyResponse]:
    """Берёт блокировки в едином порядке, чтобы параллельные решения не взаимоблокировались."""

    try:
        vacancy_id = (
            VacancyResponse.objects.only("vacancy_id").get(pk=response_id).vacancy_id
        )
        vacancy = (
            Vacancy.objects.select_for_update()
            .select_related("project")
            .get(pk=vacancy_id)
        )
        response = VacancyResponse.objects.select_for_update().get(
            pk=response_id, vacancy_id=vacancy.id
        )
    except (Vacancy.DoesNotExist, VacancyResponse.DoesNotExist) as error:
        raise NotFound() from error
    response.vacancy = vacancy
    return vacancy, response


@transaction.atomic
def create_vacancy_response(
    *, vacancy_id: int, user, validated_data: dict
) -> VacancyResponse:
    """Создаёт отклик под блокировкой вакансии и не доверяет user из payload."""

    vacancy = (
        Vacancy.objects.select_for_update().select_related("project").get(pk=vacancy_id)
    )
    if not vacancy.is_active or vacancy.project.draft or not vacancy.project.is_public:
        raise serializers.ValidationError("На эту вакансию больше нельзя откликнуться.")
    if (
        vacancy.project.leader_id == user.id
        or Collaborator.objects.filter(
            project=vacancy.project,
            user=user,
        ).exists()
    ):
        raise serializers.ValidationError(
            "Участник проекта не может откликнуться на его вакансию."
        )
    if VacancyResponse.objects.filter(vacancy=vacancy, user=user).exists():
        raise serializers.ValidationError("Вы уже откликнулись на эту вакансию.")
    response = VacancyResponse.objects.create(
        vacancy=vacancy,
        user=user,
        **validated_data,
    )
    notify_vacancy_response_created(response)
    transaction.on_commit(
        lambda: send_email.delay(
            CeleryEmailParams(
                message_type=MessageTypeEnum.RESPONDED.value,
                user_id=vacancy.project.leader_id,
                project_name=vacancy.project.name,
                project_id=vacancy.project_id,
                vacancy_role=vacancy.role,
                schema_id=2,
            )
        )
    )
    return response


def _email_payload(response: VacancyResponse, message_type: str) -> CeleryEmailParams:
    project = response.vacancy.project
    return CeleryEmailParams(
        message_type=message_type,
        user_id=response.user_id,
        project_name=project.name,
        project_id=project.id,
        vacancy_role=response.vacancy.role,
        schema_id=2,
    )


@transaction.atomic
def accept_vacancy_response(response_id: int, *, actor) -> VacancyResponse:
    """Атомарно принимает кандидата, закрывает вакансию и отклоняет остальные отклики."""

    vacancy, response = _lock_vacancy_then_response(response_id)
    _ensure_can_manage(vacancy, actor)
    if response.is_approved is not None:
        raise serializers.ValidationError("Отклик уже обработан.")
    if Collaborator.objects.filter(
        project=vacancy.project,
        user_id=response.user_id,
    ).exists():
        raise serializers.ValidationError("Пользователь уже состоит в команде проекта.")

    Collaborator.objects.create(
        project=vacancy.project,
        user_id=response.user_id,
        role=vacancy.role,
    )
    response.is_approved = True
    response.save(update_fields=("is_approved", "datetime_updated"))
    vacancy.is_active = False
    vacancy.save(update_fields=("is_active", "datetime_closed", "datetime_updated"))

    rejected = list(
        VacancyResponse.objects.select_for_update()
        .filter(vacancy=vacancy, is_approved__isnull=True)
        .exclude(pk=response.pk)
    )
    VacancyResponse.objects.filter(pk__in=[item.pk for item in rejected]).update(
        is_approved=False,
        datetime_updated=timezone.now(),
    )
    notify_vacancy_response_resolved(response, actor=actor, accepted=True)
    for rejected_response in rejected:
        rejected_response.vacancy = vacancy
        notify_vacancy_response_resolved(
            rejected_response,
            actor=actor,
            accepted=False,
        )

    transaction.on_commit(
        lambda: send_email.delay(_email_payload(response, MessageTypeEnum.ACCEPTED.value))
    )
    for rejected_response in rejected:
        rejected_response.vacancy = vacancy
        transaction.on_commit(
            lambda item=rejected_response: send_email.delay(
                _email_payload(item, MessageTypeEnum.REJECTED.value)
            )
        )
    return response


@transaction.atomic
def decline_vacancy_response(response_id: int, *, actor) -> VacancyResponse:
    """Атомарно отклоняет только ещё не обработанный отклик."""

    vacancy, response = _lock_vacancy_then_response(response_id)
    _ensure_can_manage(vacancy, actor)
    if response.is_approved is not None:
        raise serializers.ValidationError("Отклик уже обработан.")
    response.is_approved = False
    response.save(update_fields=("is_approved", "datetime_updated"))
    notify_vacancy_response_resolved(response, actor=actor, accepted=False)
    transaction.on_commit(
        lambda: send_email.delay(_email_payload(response, MessageTypeEnum.REJECTED.value))
    )
    return response


@transaction.atomic
def close_vacancy(vacancy_id: int, *, actor) -> Vacancy:
    """Закрывает вакансию и сохраняет историю, отклоняя ожидающие отклики."""

    vacancy = (
        Vacancy.objects.select_for_update().select_related("project").get(pk=vacancy_id)
    )
    _ensure_can_manage(vacancy, actor)
    if vacancy.is_active:
        vacancy.is_active = False
        vacancy.save(update_fields=("is_active", "datetime_closed", "datetime_updated"))
        pending_responses = list(
            VacancyResponse.objects.select_for_update().filter(
                vacancy=vacancy,
                is_approved__isnull=True,
            )
        )
        VacancyResponse.objects.filter(
            vacancy=vacancy,
            is_approved__isnull=True,
        ).update(is_approved=False, datetime_updated=timezone.now())
        for response in pending_responses:
            response.vacancy = vacancy
            notify_vacancy_response_resolved(response, actor=actor, accepted=False)
    return vacancy


@transaction.atomic
def reopen_vacancy(vacancy_id: int, *, actor) -> Vacancy:
    """Возобновляет вакансию только у опубликованного публичного проекта."""

    vacancy = (
        Vacancy.objects.select_for_update().select_related("project").get(pk=vacancy_id)
    )
    _ensure_can_manage(vacancy, actor)
    if vacancy.project.draft or not vacancy.project.is_public:
        raise serializers.ValidationError(
            "Возобновить вакансию можно только в опубликованном публичном проекте."
        )
    if not vacancy.is_active:
        vacancy.is_active = True
        vacancy.save(update_fields=("is_active", "datetime_closed", "datetime_updated"))
    return vacancy


@transaction.atomic
def delete_vacancy_without_responses(vacancy_id: int, *, actor) -> None:
    """Удаляет вакансию под блокировкой, не допуская потери истории откликов."""

    vacancy = (
        Vacancy.objects.select_for_update().select_related("project").get(pk=vacancy_id)
    )
    _ensure_can_manage(vacancy, actor)
    if VacancyResponse.objects.filter(vacancy=vacancy).exists():
        raise serializers.ValidationError(
            "Вакансию с откликами нельзя удалить. Закройте её."
        )
    vacancy.delete()
