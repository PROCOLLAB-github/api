from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction

from partner_programs.models import Application, Submission, TeamMember
from projects.models import Collaborator, Project, ProjectLink


class SubmissionProjectError(Exception):
    """Доменная ошибка создания постоянного Project из Submission."""


class SubmissionProjectAccessError(SubmissionProjectError):
    """Пользователь не может создавать Project из указанного Submission."""


class SubmissionProjectStatusError(SubmissionProjectError):
    """Текущий статус Submission не допускает создание Project."""


@dataclass(frozen=True)
class SubmissionProjectResult:
    project: Project
    created: bool


def _valid_submission_links(links):
    """Возвращает уникальные HTTP(S)-ссылки без падения на старых JSON-данных."""
    if not isinstance(links, list):
        return []

    validator = URLValidator(schemes=("http", "https"))
    max_length = ProjectLink._meta.get_field("link").max_length
    result = []
    for raw_link in links:
        if not isinstance(raw_link, str):
            continue
        link = raw_link.strip()
        if not link or len(link) > max_length or link in result:
            continue
        try:
            validator(link)
        except ValidationError:
            continue
        result.append(link)
    return result


@transaction.atomic
def create_project_from_submission(*, submission_id, actor):
    """Идемпотентно создает Project из зафиксированного Submission.

    Submission остается историческим снимком решения. Повторные версии одной
    Application используют одну связь Application.project и не клонируют Project.
    """
    submission = (
        Submission.objects.select_for_update()
        .select_related("application")
        .get(pk=submission_id)
    )
    application = (
        Application.objects.select_for_update()
        .select_related("user", "project")
        .get(pk=submission.application_id)
    )

    if not (actor.is_staff or actor.is_superuser or application.user_id == actor.pk):
        raise SubmissionProjectAccessError()

    if submission.status not in (
        Submission.STATUS_SUBMITTED,
        Submission.STATUS_FINAL,
    ):
        raise SubmissionProjectStatusError(
            "Создать проект можно только из отправленного или финального решения."
        )

    if application.project_id:
        return SubmissionProjectResult(project=application.project, created=False)

    project = Project.objects.create(
        leader=application.user,
        name=submission.title,
        description=submission.description,
        draft=True,
        is_public=False,
    )
    ProjectLink.objects.bulk_create(
        [
            ProjectLink(project=project, link=link)
            for link in _valid_submission_links(submission.links)
        ],
        ignore_conflicts=True,
    )

    application.project = project
    application.save(update_fields=["project", "updated_at"])

    if application.participation_mode == Application.PARTICIPATION_MODE_TEAM:
        accepted_members = (
            TeamMember.objects.select_for_update()
            .filter(
                team__application=application,
                status=TeamMember.STATUS_ACCEPTED,
            )
            .exclude(user_id=application.user_id)
        )
        for member in accepted_members.select_related("user"):
            Collaborator.objects.get_or_create(
                project=project,
                user=member.user,
                defaults={"role": "Участник команды"},
            )

    return SubmissionProjectResult(project=project, created=True)
