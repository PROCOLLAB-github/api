"""Creation and first publication; existing program editors remain authoritative."""

import hashlib
import json
import copy
from html import unescape

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from partner_programs.models import PartnerProgram, ProgramRegistration
from partner_programs.permissions import require_create_program
from partner_programs.services.management import managed_program
from partner_programs.serializers.management import BASIC_FIELDS, DATE_FIELDS
from partner_programs.services import native_registration as registration
from project_rates.workspace import WorkspaceConflict

FORMATS = ("case_championship", "hackathon", "noncompetitive")


def summary(program):
    return {
        "id": program.pk,
        "name": program.name,
        "draft": program.draft,
        "program_format": program.program_format,
        "solution_storage_mode": program.solution_storage_mode,
        "updated_at": program.datetime_updated,
        "datetime_started": program.datetime_started,
        "datetime_finished": program.datetime_finished,
        "datetime_registration_ends": program.datetime_registration_ends,
    }


@transaction.atomic
def create_program(user, data):
    # Serialize retries per creator; the database constraint also covers other writers.
    actor = get_user_model().objects.select_for_update().get(pk=user.pk)
    require_create_program(actor)
    fingerprint = hashlib.sha256(
        json.dumps([data["name"], data["format"]], ensure_ascii=False).encode()
    ).hexdigest()
    previous = PartnerProgram.objects.filter(
        created_by=actor, creation_key=data["idempotency_key"]
    ).first()
    if previous:
        if previous.creation_fingerprint != fingerprint:
            raise WorkspaceConflict(
                "creation_key_reused",
                "Этот запрос уже создал другую программу. Обновите форму создания.",
            )
        return previous, False
    competitive = data["format"] != "noncompetitive"
    program = PartnerProgram.objects.create(
        name=data["name"],
        tag="",
        city="",
        draft=True,
        program_format=data["format"],
        created_by=actor,
        creation_key=data["idempotency_key"],
        creation_fingerprint=fingerprint,
        is_competitive=competitive,
        solution_storage_mode="solution" if competitive else "legacy_project",
        solution_template=data["format"] if competitive else None,
        # Only a new program opts in. Existing switches and operator rollback stay intact.
        solution_creation_enabled=competitive,
    )
    program.managers.add(actor)
    return program, True


def preview_program(pk, user, request):
    from partner_programs.serializers import PartnerProgramForMemberSerializer

    program = managed_program(pk, user)
    data = PartnerProgramForMemberSerializer(
        program, context={"request": request, "user": user, "program_user_profile": None}
    ).data
    # Read-only participant presentation, never an enrollment or an authorization grant.
    data.update(
        preview=True,
        draft=program.draft,
        is_user_manager=False,
        is_user_expert=False,
        is_user_member=True,
        current_application=None,
        pending_expert_invitation_id=None,
    )
    participant = {
        "case_provided": program.fields.filter(name="case").exists(),
        "case_name": None,
        "stage": "none" if program.is_competitive else "not_applicable",
        "submission_open": program.is_project_submission_open(),
    }
    participant[
        "application"
        if program.solution_storage_mode == "solution"
        else "participant_project"
    ] = None
    data["preview_widget"] = {
        "program_id": program.pk,
        "role": "participant",
        "is_competitive": program.is_competitive,
        "storage_mode": program.solution_storage_mode,
        "participant": participant,
    }
    if program.solution_storage_mode == "solution":
        from partner_programs.solution_api import context_data

        context = context_data(program, user, preview_participant=True)
        data["solution_action_available"] = context["can_create"]
        data["solution_action_blocked_reason"] = context["blocked_reason"]
    return data


def _revision(program, config):
    values = {
        "program": {
            name: getattr(program, name) for name in (*BASIC_FIELDS, *DATE_FIELDS)
        },
        "updated_at": program.datetime_updated,
        "registration": {
            "revision": config.revision,
            "draft": config.draft,
            "external_status": config.external_status,
            "external_url": config.external_url,
        }
        if config
        else None,
    }
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, default=str).encode()
    ).hexdigest()


def _registration_problem(config):
    if config is None:
        return "Выберите способ регистрации и сохраните анкету."
    try:
        schema = registration.clean_schema(config.draft, publishing=True)
    except ValidationError as error:
        detail = error.detail
        return " ".join(map(str, detail)) if isinstance(detail, list) else str(detail)
    if schema["mode"] == "external":
        if config.external_status != "connected":
            return "Дождитесь подключения внешней формы администратором."
        try:
            URLValidator(schemes=("http", "https"))(config.external_url)
        except DjangoValidationError:
            return "Администратору нужно проверить адрес подключенной формы."
    return None


def _date_problem(program):
    if any(
        getattr(program, field) is None
        for field in (
            "datetime_started",
            "datetime_finished",
            "datetime_registration_ends",
        )
    ):
        return "Укажите начало, окончание программы и окончание регистрации."
    if program.datetime_finished <= program.datetime_started:
        return "Окончание программы должно быть позже начала."
    if program.datetime_registration_ends <= timezone.now():
        return "Окончание регистрации должно быть в будущем, чтобы открыть прием."
    if program.datetime_registration_ends > program.datetime_finished:
        return "Регистрация должна завершиться не позже окончания программы."
    return None


def readiness_data(program, config=None):
    if config is None:
        config = registration.config_for(program)
    page_problem = (
        None
        if program.name.strip()
        and unescape(strip_tags(program.description or "")).strip()
        else "Заполните название и описание программы."
    )
    checks = []
    blockers = []
    for code, title, section, problem, ready_detail in (
        (
            "page",
            "Страница программы",
            "basic",
            page_problem,
            "Название и описание заполнены. Обложку можно добавить позже.",
        ),
        (
            "dates",
            "Сроки",
            "dates",
            _date_problem(program),
            "Сроки программы и регистрации сохранены.",
        ),
        (
            "registration",
            "Регистрация",
            "registration",
            _registration_problem(config),
            "Способ регистрации и анкета готовы.",
        ),
    ):
        checks.append(
            dict(
                code=code,
                title=title,
                section=section,
                ready=problem is None,
                detail=problem or ready_detail,
            )
        )
        if problem:
            blockers.append(dict(code=code, section=section, detail=problem))
    return {
        "program": summary(program),
        "revision": _revision(program, config),
        "checks": checks,
        "blockers": blockers,
        "warnings": [
            "Форму решения, критерии и экспертов можно настроить после публикации."
        ]
        if program.is_competitive
        else [],
        "can_publish": program.draft and not blockers,
        "links": {
            "program": f"{registration.frontend_url()}/office/program/{program.pk}",
            "registration": registration.public_link(program)
            if not program.draft
            else None,
        },
    }


def readiness(pk, user):
    return readiness_data(managed_program(pk, user))


@transaction.atomic
def publish_program(pk, user, revision):
    program = managed_program(pk, user, lock=True)
    config = (
        ProgramRegistration.objects.select_for_update().filter(program=program).first()
    )
    program._native_registration_config = config
    state = readiness_data(program, config)
    if not program.draft:
        # Retry after a lost response never publishes a second questionnaire version.
        return state
    if state["revision"] != revision:
        raise WorkspaceConflict(
            "stale_program_launch",
            "Настройки изменились. Обновите данные и повторите проверку.",
        )
    if state["blockers"]:
        raise ValidationError(
            {
                "code": "program_not_ready",
                "detail": "Завершите обязательные настройки программы.",
                "blockers": state["blockers"],
            }
        )
    schema = registration.clean_schema(config.draft, publishing=True)
    config.published = copy.deepcopy(schema)
    config.published_at = timezone.now()
    config.published_version += 1
    config.revision += 1
    config.save(
        update_fields=["published", "published_at", "published_version", "revision"]
    )
    program.draft = False
    program.save(update_fields=["draft", "datetime_updated"])
    return readiness_data(program, config)
