import logging
from collections import OrderedDict
from uuid import UUID

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import CharField
from django.db.models import Prefetch
from django.db.models.functions import Cast
from django.template.loader import render_to_string
from django.utils import timezone

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramInvite,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.privacy import (
    collect_privacy_blockers,
    has_privacy_blockers,
)
from project_rates.models import Criteria, ProjectScore
from projects.models import Project

logger = logging.getLogger()

DEFAULT_INVITE_EXPIRATION_DAYS = 30

READINESS_LABELS = {
    "basic_info": "Основная информация",
    "dates": "Сроки и формат",
    "registration": "Регистрация",
    "legal_terms": "Правовые документы",
    "materials": "Материалы",
    "criteria_experts": "Критерии и эксперты",
    "visual_assets": "Основная обложка",
    "certificate_template": "Сертификат",
    "verification": "Верификация",
}
MODERATION_REQUIRED_KEYS = PartnerProgram.MODERATION_REQUIRED_SECTIONS
READINESS_WEIGHTS = PartnerProgram.READINESS_WEIGHTS
READINESS_ROUTES = {
    "basic_info": "main",
    "dates": "schedule",
    "registration": "registration",
    "legal_terms": "registration",
    "materials": "materials",
    "criteria_experts": "criteria",
    "visual_assets": "main",
    "verification": "verification",
    "certificate_template": "certificate",
}
OPERATIONAL_ITEMS = (
    {
        "key": "materials",
        "label": "Материалы",
        "deadline": "До старта чемпионата",
    },
    {
        "key": "criteria_experts",
        "label": "Критерии и эксперты",
        "deadline": "До этапа оценки",
    },
    {
        "key": "certificate_template",
        "label": "Сертификат",
        "deadline": "До завершения, если нужен",
        "optional": True,
    },
    {
        "key": "verification",
        "label": "Верификация организатора",
        "deadline": "До публикации желательно",
        "optional": True,
    },
)


class ProgramInviteError(Exception):
    status_code = 400


class ProgramInviteNotFoundError(ProgramInviteError):
    status_code = 404


class ProgramInviteGoneError(ProgramInviteError):
    status_code = 410

    def __init__(self, invite: PartnerProgramInvite, message: str):
        self.invite = invite
        super().__init__(message)


def _readiness_percentage(checklist: dict, required_keys: list[str]) -> int:
    if not required_keys:
        return 100
    completed = sum(1 for key in required_keys if checklist.get(key) is True)
    return round(completed / len(required_keys) * 100)


def _weighted_readiness_percent(checklist: dict) -> int:
    percentage = sum(
        weight
        for key, weight in READINESS_WEIGHTS.items()
        if checklist.get(key) is True or checklist.get(key) == "not_applicable"
    )
    return max(0, min(100, int(percentage)))


def _section_is_ready(value) -> bool:
    return value is True or value == "not_applicable"


def _basic_info_missing_fields(program: PartnerProgram) -> list[str]:
    missing = []
    description = (program.description or "").strip()
    if not (program.name or "").strip():
        missing.append("name")
    if not description or len(description) < 180:
        missing.append("description")
    if not (program.city or "").strip():
        missing.append("city")
    return missing


def _dates_missing_fields(program: PartnerProgram) -> list[str]:
    missing = []
    if not program.datetime_started:
        missing.append("datetime_started")
    if not program.datetime_registration_ends:
        missing.append("datetime_registration_ends")
    if not program.datetime_project_submission_ends:
        missing.append("datetime_project_submission_ends")
    if not program.datetime_finished:
        missing.append("datetime_finished")
    if missing:
        return missing

    if (
        program.datetime_started > program.datetime_finished
        or program.datetime_registration_ends > program.datetime_project_submission_ends
        or program.datetime_project_submission_ends > program.datetime_finished
        or (
            program.datetime_evaluation_ends
            and not (
                program.datetime_project_submission_ends
                <= program.datetime_evaluation_ends
                <= program.datetime_finished
            )
        )
    ):
        missing.append("date_order")
    return missing


def _legal_terms_missing_fields(privacy_blockers: dict) -> list[str]:
    missing = []
    if privacy_blockers.get("missing_legal_documents"):
        missing.append("active_legal_documents")
    if privacy_blockers.get("organizer_terms_not_accepted"):
        missing.append("organizer_terms")
    if privacy_blockers.get("forbidden_registration_fields"):
        missing.append("privacy_safe_registration_fields")
    return missing


def _criteria_experts_missing_fields(program: PartnerProgram, value) -> list[str]:
    if value == "not_applicable":
        return []
    missing = []
    if not program.is_competitive:
        return missing
    user_criteria = Criteria.objects.filter(partner_program=program).exclude(
        name="РљРѕРјРјРµРЅС‚Р°СЂРёР№"
    )
    if not user_criteria.exists():
        missing.append("criteria")
    elif sum(criteria.weight for criteria in user_criteria) != 100:
        missing.append("criteria_weight_sum")
    if not program.experts.exists():
        missing.append("experts")
    return missing


def _section_missing_fields(
    program: PartnerProgram,
    key: str,
    value,
    privacy_blockers: dict,
) -> list[str]:
    if _section_is_ready(value):
        return []
    if key == "basic_info":
        return _basic_info_missing_fields(program)
    if key == "dates":
        return _dates_missing_fields(program)
    if key == "registration":
        return ["registration_link", "data_schema"]
    if key == "legal_terms":
        return _legal_terms_missing_fields(privacy_blockers)
    if key == "materials":
        return ["materials"]
    if key == "criteria_experts":
        return _criteria_experts_missing_fields(program, value)
    if key == "visual_assets":
        return ["cover_image_address", "image_address"]
    if key == "verification":
        return ["verification_status"]
    if key == "certificate_template":
        return ["certificate_template"]
    return [key]


def _readiness_sections(
    program: PartnerProgram,
    checklist: dict,
    privacy_blockers: dict,
) -> list[dict]:
    sections = []
    for key, weight in READINESS_WEIGHTS.items():
        value = checklist.get(key, False)
        missing_fields = _section_missing_fields(
            program,
            key,
            value,
            privacy_blockers,
        )
        section = {
            "id": key,
            "label": READINESS_LABELS.get(key, key),
            "is_ready": _section_is_ready(value),
            "weight": weight,
            "blocking_for_moderation": key in MODERATION_REQUIRED_KEYS,
            "missing_fields": missing_fields,
            "route": READINESS_ROUTES.get(key, "main"),
            "section": READINESS_ROUTES.get(key, "main"),
        }
        if value == "not_applicable":
            section["not_applicable"] = True
        if missing_fields:
            section["missing_reason"] = ", ".join(missing_fields)
        sections.append(section)
    return sections


def _operational_required_keys(program: PartnerProgram) -> list[str]:
    keys = ["materials"]
    if program.is_competitive:
        keys.append("criteria_experts")
    return keys


def get_program_readiness_payload(program: PartnerProgram) -> dict:
    checklist = program.calculate_readiness()
    privacy_blockers = collect_privacy_blockers(program)
    checklist["legal_terms"] = not has_privacy_blockers(privacy_blockers)

    moderation_required_keys = list(MODERATION_REQUIRED_KEYS)
    moderation_missing = [
        key for key in moderation_required_keys if checklist.get(key) is not True
    ]
    moderation_percentage = _readiness_percentage(checklist, moderation_required_keys)
    readiness_percent = _weighted_readiness_percent(checklist)
    sections = _readiness_sections(program, checklist, privacy_blockers)

    operational_required_keys = _operational_required_keys(program)
    operational_missing = [
        key
        for key in operational_required_keys
        if checklist.get(key) not in (True, "not_applicable")
    ]
    operational_items = []
    for item in OPERATIONAL_ITEMS:
        key = item["key"]
        value = checklist.get(key)
        operational_items.append(
            {
                **item,
                "status": value,
                "is_ready": value in (True, "not_applicable"),
            }
        )

    readiness_to_moderation = {
        "percentage": moderation_percentage,
        "checklist": {key: checklist.get(key, False) for key in moderation_required_keys},
        "labels": {key: READINESS_LABELS[key] for key in moderation_required_keys},
        "required_keys": moderation_required_keys,
        "missing_required_sections": moderation_missing,
        "is_ready": not moderation_missing,
    }
    operational_keys = (
        "materials",
        "criteria_experts",
        "certificate_template",
        "verification",
    )
    operational_readiness = {
        "percentage": _readiness_percentage(checklist, operational_required_keys),
        "checklist": {key: checklist.get(key, False) for key in operational_keys},
        "labels": {key: READINESS_LABELS[key] for key in operational_keys},
        "required_keys": operational_required_keys,
        "missing_required_sections": operational_missing,
        "items": operational_items,
        "is_ready": not operational_missing,
    }

    return {
        "readiness_percent": readiness_percent,
        "percentage": readiness_percent,
        "checklist": checklist,
        "labels": READINESS_LABELS,
        "sections": sections,
        "required_sections": moderation_required_keys,
        "missing_required_sections": moderation_missing,
        "privacy_blockers": privacy_blockers,
        "can_submit_to_moderation": (
            program.status
            in (PartnerProgram.STATUS_DRAFT, PartnerProgram.STATUS_REJECTED)
            and not moderation_missing
        ),
        "status": program.status,
        "readiness_to_moderation": readiness_to_moderation,
        "operational_readiness": operational_readiness,
    }


def get_moderation_submission_errors(program: PartnerProgram) -> dict[str, str]:
    readiness = get_program_readiness_payload(program)
    return {
        key: "Раздел обязателен для отправки на модерацию"
        for key in readiness["readiness_to_moderation"]["missing_required_sections"]
    }


def build_program_invite_url(token) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/invite/{token}/"


def create_program_invites(
    *,
    program: PartnerProgram,
    emails: list[str],
    created_by,
    expires_in_days: int = DEFAULT_INVITE_EXPIRATION_DAYS,
    custom_message: str = "",
) -> list[PartnerProgramInvite]:
    if not program.is_private:
        raise ProgramInviteError(
            "Приглашения можно выпускать только для закрытого чемпионата."
        )

    expires_at = timezone.now() + timezone.timedelta(days=expires_in_days)
    invites = []
    for email in emails:
        invite = PartnerProgramInvite.objects.create(
            program=program,
            email=email,
            created_by=created_by,
            expires_at=expires_at,
        )
        send_program_invite_email(invite, custom_message=custom_message)
        invites.append(invite)
    return invites


def send_program_invite_email(
    invite: PartnerProgramInvite,
    *,
    custom_message: str = "",
) -> int:
    program = invite.program
    subject = f"Приглашение в закрытый чемпионат «{program.name}»"
    context = {
        "invite": invite,
        "program": program,
        "organizer_name": get_program_organizer_name(program),
        "accept_url": build_program_invite_url(invite.token),
        "invite_code": str(invite.token),
        "short_invite_code": str(invite.token).split("-", 1)[0],
        "custom_message": custom_message,
        "description": (program.description or "")[:500],
    }
    message = render_to_string("partner_programs/email/invite.txt", context)
    return send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", settings.EMAIL_USER),
        recipient_list=[invite.email],
        fail_silently=True,
    )


def get_program_organizer_name(program: PartnerProgram) -> str:
    if program.company_id:
        return program.company.name
    manager = program.managers.order_by("id").first()
    if manager:
        full_name = manager.get_full_name()
        return full_name or manager.email
    return "Команда PROCOLLAB"


def resolve_program_invite_token(token: str) -> PartnerProgramInvite:
    normalized_token = (token or "").strip()
    if not normalized_token:
        raise ProgramInviteNotFoundError("Приглашение не найдено или недействительно.")

    qs = PartnerProgramInvite.objects.select_related(
        "program__company",
        "accepted_by",
        "created_by",
    )
    try:
        invite_uuid = UUID(normalized_token)
        invite = qs.filter(token=invite_uuid).first()
    except ValueError:
        if len(normalized_token) < 8:
            invite = None
        else:
            matches = list(
                qs.annotate(token_text=Cast("token", output_field=CharField()))
                .filter(token_text__istartswith=normalized_token)
                .order_by("id")[:2]
            )
            invite = matches[0] if len(matches) == 1 else None

    if invite is None:
        raise ProgramInviteNotFoundError("Приглашение не найдено или недействительно.")
    return invite


def ensure_program_invite_can_be_used(invite: PartnerProgramInvite) -> None:
    if invite.status != PartnerProgramInvite.STATUS_PENDING:
        raise ProgramInviteGoneError(
            invite,
            f"Приглашение уже не активно: {invite.get_status_display()}.",
        )
    if invite.is_expired:
        invite.status = PartnerProgramInvite.STATUS_EXPIRED
        invite.save(update_fields=["status", "datetime_updated"])
        raise ProgramInviteGoneError(invite, "Срок действия приглашения истёк.")


def get_active_program_invite(token: str) -> PartnerProgramInvite:
    invite = resolve_program_invite_token(token)
    ensure_program_invite_can_be_used(invite)
    return invite


def accept_program_invite(*, token: str, user) -> PartnerProgramInvite:
    with transaction.atomic():
        invite = (
            PartnerProgramInvite.objects.select_for_update()
            .select_related("program")
            .get(pk=resolve_program_invite_token(token).pk)
        )
        ensure_program_invite_can_be_used(invite)

        PartnerProgramUserProfile.objects.get_or_create(
            partner_program=invite.program,
            user=user,
            defaults={"partner_program_data": {"invite_token": str(invite.token)}},
        )
        invite.status = PartnerProgramInvite.STATUS_USED
        invite.accepted_at = timezone.now()
        invite.accepted_by = user
        invite.save(
            update_fields=[
                "status",
                "accepted_at",
                "accepted_by",
                "datetime_updated",
            ]
        )
        return invite


def revoke_program_invite(invite: PartnerProgramInvite) -> PartnerProgramInvite:
    ensure_program_invite_can_be_used(invite)
    invite.status = PartnerProgramInvite.STATUS_REVOKED
    invite.save(update_fields=["status", "datetime_updated"])
    return invite


def resend_program_invite(
    invite: PartnerProgramInvite,
    *,
    expires_in_days: int | None = None,
    custom_message: str = "",
) -> PartnerProgramInvite:
    if invite.status == PartnerProgramInvite.STATUS_REVOKED:
        raise ProgramInviteGoneError(
            invite,
            "Отозванное приглашение нельзя отправить повторно.",
        )

    if invite.status == PartnerProgramInvite.STATUS_USED:
        raise ProgramInviteGoneError(
            invite,
            "Использованное приглашение нельзя отправить повторно.",
        )

    if invite.status == PartnerProgramInvite.STATUS_EXPIRED or invite.is_expired:
        invite.status = PartnerProgramInvite.STATUS_PENDING

    if expires_in_days is not None:
        invite.expires_at = timezone.now() + timezone.timedelta(days=expires_in_days)
    elif invite.expires_at <= timezone.now():
        invite.expires_at = timezone.now() + timezone.timedelta(
            days=DEFAULT_INVITE_EXPIRATION_DAYS
        )

    invite.save(update_fields=["status", "expires_at", "datetime_updated"])
    send_program_invite_email(invite, custom_message=custom_message)
    return invite


def publish_finished_program_projects(now=None) -> int:
    if now is None:
        now = timezone.now()

    program_ids = PartnerProgram.objects.filter(
        publish_projects_after_finish=True,
        datetime_finished__lte=now,
    ).values_list("id", flat=True)
    if not program_ids.exists():
        return 0

    link_project_ids = PartnerProgramProject.objects.filter(
        partner_program_id__in=program_ids
    ).values_list("project_id", flat=True)
    profile_project_ids = PartnerProgramUserProfile.objects.filter(
        partner_program_id__in=program_ids,
        project_id__isnull=False,
    ).values_list("project_id", flat=True)
    project_ids = link_project_ids.union(profile_project_ids)

    return Project.objects.filter(
        id__in=project_ids,
        is_public=False,
        draft=False,
    ).update(is_public=True)


class ProjectScoreDataPreparer:
    """
    Data preparer about project_rates by experts.
    """

    USER_ERROR_FIELDS = {
        "Фамилия": "ОШИБКА",
        "Имя": "ОШИБКА",
        "Отчество": "ОШИБКА",
        "Email": "ОШИБКА",
        "Регион_РФ": "ОШИБКА",
        "Учебное_заведение": "ОШИБКА",
        "Название_учебного_заведения": "ОШИБКА",
        "Класс_курс": "ОШИБКА",
    }

    EXPERT_ERROR_FIELDS = {"Фамилия эксперта": "ОШИБКА"}

    def __init__(
        self,
        user_profiles: dict[int, PartnerProgramUserProfile],
        scores: dict[int, list[ProjectScore]],
        project_id: int,
        program_id: int,
    ):
        self._project_id = project_id
        self._user_profiles = user_profiles
        self._scores = scores
        self._program_id = program_id

    def get_project_user_info(self) -> dict[str, str]:
        try:
            user_program_profile: PartnerProgramUserProfile = self._user_profiles.get(
                self._project_id
            )
            user_program_profile_json: dict = (
                user_program_profile.partner_program_data if user_program_profile else {}
            )

            user_info: dict[str, str] = {
                "Фамилия": (
                    user_program_profile.user.last_name if user_program_profile else ""
                ),
                "Имя": (
                    user_program_profile.user.first_name if user_program_profile else ""
                ),
                "Отчество": (
                    user_program_profile.user.patronymic if user_program_profile else ""
                ),
                "Email": (
                    user_program_profile_json.get("email")
                    if user_program_profile_json.get("email")
                    else user_program_profile.user.email
                ),
                "Регион_РФ": user_program_profile_json.get("region", ""),
                "Учебное_заведение": user_program_profile_json.get("education_type", ""),
                "Название_учебного_заведения": user_program_profile_json.get(
                    "institution_name", ""
                ),
                "Класс_курс": user_program_profile_json.get("class_course", ""),
            }
            return user_info
        except Exception as e:
            logger.error(
                f"Prepare export rates data about user error: {str(e)}", exc_info=True
            )
            return self.USER_ERROR_FIELDS

    def get_project_expert_info(self) -> dict[str, str]:
        try:
            project_scores: list[ProjectScore] = self._scores.get(self._project_id, [])
            first_score = project_scores[0] if project_scores else None
            expert_last_name: dict[str, str] = {
                "Фамилия эксперта": first_score.user.last_name if first_score else ""
            }
            return expert_last_name
        except Exception as e:
            logger.error(
                f"Prepare export rates data about expert error: {str(e)}", exc_info=True
            )
            return self.EXPERT_ERROR_FIELDS

    def get_project_scores_info(self) -> dict[str, str]:
        try:
            project_scores_dict = {}
            project_scores: list[ProjectScore] = self._scores.get(self._project_id, [])
            score_info_with_out_comment: dict[str, str] = {
                score.criteria.name: score.value
                for score in project_scores
                if score.criteria.name != "Комментарий"
            }
            project_scores_dict.update(score_info_with_out_comment)
            comment = next(
                (
                    score
                    for score in project_scores
                    if score.criteria.name == "Комментарий"
                ),
                None,
            )
            if comment is not None:
                project_scores_dict["Комментарий"] = comment.value
            return project_scores_dict
        except Exception as e:
            logger.error(
                f"Prepare export rates data about project_scores error: {str(e)}",
                exc_info=True,
            )
            return {
                criteria.name: "ОШИБКА"
                for criteria in Criteria.objects.filter(
                    partner_program__id=self._program_id
                )
            }


BASE_COLUMNS = [
    ("row_number", "№ п/п"),
    ("project_name", "Название проекта"),
    ("project_description", "Описание проекта"),
    ("project_region", "Регион проекта"),
    ("project_presentation", "Ссылка на презентацию"),
    ("team_size", "Количество человек в команде"),
    ("team_members", "Состав команды"),
    ("leader_full_name", "Имя фамилия лидера"),
]


def _leader_full_name(user):
    if not user:
        return ""
    if hasattr(user, "get_full_name") and callable(user.get_full_name):
        full = user.get_full_name()
        if full:
            return full
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    return (first + " " + last).strip() or getattr(user, "username", "") or str(user.pk)


def _calc_team_size(project):
    member_keys: set[tuple[str, int | str]] = set()

    leader_id = getattr(project, "leader_id", None)
    if leader_id is not None:
        member_keys.add(("user", leader_id))
    elif getattr(project, "leader", None) is not None:
        member_keys.add(("object", str(id(project.leader))))

    collaborators = getattr(project, "_prefetched_collaborators", None)
    try:
        if collaborators is None and hasattr(project, "collaborator_set"):
            collaborators = project.collaborator_set.select_related("user").all()
        elif collaborators is None and hasattr(project, "get_collaborators_user_list"):
            collaborators = project.get_collaborators_user_list()
    except Exception:
        collaborators = []

    for collaborator in collaborators or []:
        user = getattr(collaborator, "user", collaborator)
        user_id = getattr(user, "id", None)
        if user_id is not None:
            member_keys.add(("user", user_id))
        elif user is not None:
            member_keys.add(("object", str(id(user))))

    return len(member_keys) or 1


def validate_project_team_size_for_program(
    *, program: PartnerProgram, project: Project
) -> None:
    """Validate a linked project against the championship participation rules."""
    team_size = _calc_team_size(project)

    if (
        program.participation_format == PartnerProgram.PARTICIPATION_FORMAT_INDIVIDUAL
        and team_size != 1
    ):
        raise ValueError(
            "For individual participation, the project must have exactly one member."
        )

    if program.participation_format == PartnerProgram.PARTICIPATION_FORMAT_TEAM:
        min_size = program.project_team_min_size or 1
        max_size = program.project_team_max_size
        if team_size < min_size:
            raise ValueError(
                f"The project team must include at least {min_size} member(s)."
            )
        if max_size is not None and team_size > max_size:
            raise ValueError(
                f"The project team must include no more than {max_size} member(s)."
            )


def _team_members(project) -> str:
    members: list[str] = []
    seen_ids: set[int | None] = set()

    leader = getattr(project, "leader", None)
    if leader:
        leader_name = _leader_full_name(leader)
        if leader_name:
            members.append(leader_name)
        seen_ids.add(getattr(leader, "id", None))

    collaborators = getattr(project, "_prefetched_collaborators", None)
    if collaborators is None:
        collaborators = (
            project.collaborator_set.select_related("user").all()
            if hasattr(project, "collaborator_set")
            else []
        )

    for collaborator in collaborators:
        user = getattr(collaborator, "user", None)
        if not user:
            continue
        user_id = getattr(user, "id", None)
        if user_id in seen_ids:
            continue
        name = _leader_full_name(user)
        if not name:
            continue
        members.append(name)
        seen_ids.add(user_id)

    return "\n".join(members)


def build_program_field_columns(program) -> list[tuple[str, str]]:
    program_fields = program.fields.all().order_by("pk")
    return [
        (f"name:{program_field.name}", program_field.label)
        for program_field in program_fields
    ]


def row_dict_for_link(
    program_project_link,
    extra_field_keys_order: list[str],
    row_number: int,
) -> OrderedDict:
    """
    program_project_link: PartnerProgramProject
    extra_field_keys_order: список псевдоключей "name:<field.name>" в нужном порядке
    row_number: порядковый номер строки в Excel (начиная с 1)
    """
    project = program_project_link.project
    row = OrderedDict()

    row["row_number"] = row_number

    row["project_name"] = project.name or ""
    row["project_description"] = project.description or ""
    row["project_region"] = project.region or ""
    row["project_presentation"] = project.presentation_address or ""
    row["team_size"] = _calc_team_size(project)
    row["team_members"] = _team_members(project)
    row["leader_full_name"] = _leader_full_name(getattr(project, "leader", None))

    values_map: dict[str, str] = {}
    prefetched_values = getattr(program_project_link, "_prefetched_field_values", None)
    field_values_iterable = (
        prefetched_values
        if prefetched_values is not None
        else program_project_link.field_values.all()
    )

    for field_value in field_values_iterable:
        if (
            field_value.field.partner_program_id
            == program_project_link.partner_program_id
        ):
            values_map[f"name:{field_value.field.name}"] = field_value.get_value()

    for field_key in extra_field_keys_order:
        row[field_key] = values_map.get(field_key, "")

    return row


def prepare_project_scores_export_data(program_id: int) -> list[dict]:
    """
    Готовит данные для выгрузки оценок проектов.
    Порядок колонок: название проекта → фамилия эксперта → доп. поля программы →
    критерии → комментарий.
    Если у проекта несколько экспертов, на каждый проект-эксперт создаётся отдельная строка.
    """
    criterias = list(
        Criteria.objects.filter(partner_program__id=program_id)
        .select_related("partner_program")
        .order_by("id")
    )
    if not criterias:
        return []

    comment_criteria = next(
        (criteria for criteria in criterias if criteria.name == "Комментарий"),
        None,
    )
    criterias_without_comment = [
        criteria for criteria in criterias if criteria != comment_criteria
    ]

    program_fields = list(
        PartnerProgramField.objects.filter(partner_program_id=program_id).order_by("id")
    )

    scores = (
        ProjectScore.objects.filter(criteria__in=criterias)
        .select_related("user", "criteria", "project")
        .order_by("project_id", "criteria_id", "id")
    )
    scores_dict: dict[int, list[ProjectScore]] = {}
    for score in scores:
        scores_dict.setdefault(score.project_id, []).append(score)

    if not scores_dict:
        empty_row: dict[str, str] = {
            "Название проекта": "",
            "Фамилия эксперта": "",
        }
        for field in program_fields:
            empty_row[field.label] = ""
        for criteria in criterias_without_comment:
            empty_row[criteria.name] = ""
        if comment_criteria:
            empty_row["Комментарий"] = ""
        return [empty_row]

    project_ids = list(scores_dict.keys())

    field_values_prefetch = Prefetch(
        "field_values",
        queryset=PartnerProgramFieldValue.objects.select_related("field").filter(
            program_project__partner_program_id=program_id,
            program_project__project_id__in=project_ids,
        ),
        to_attr="_prefetched_field_values",
    )
    program_projects = (
        PartnerProgramProject.objects.filter(
            partner_program_id=program_id, project_id__in=project_ids
        )
        .select_related("project")
        .prefetch_related(field_values_prefetch)
    )
    program_project_by_project_id: dict[int, PartnerProgramProject] = {
        link.project_id: link for link in program_projects
    }

    prepared_projects_rates_data: list[dict] = []
    for project_id, project_scores in scores_dict.items():
        project_link = program_project_by_project_id.get(project_id)
        project = (
            project_link.project
            if project_link
            else (project_scores[0].project if project_scores else None)
        )

        field_values_map: dict[int, str] = {}
        field_values = (
            getattr(project_link, "_prefetched_field_values", None)
            if project_link
            else None
        )
        if field_values:
            for field_value in field_values:
                field_values_map[field_value.field_id] = field_value.get_value()

        scores_by_expert: dict[int, list[ProjectScore]] = {}
        for score in project_scores:
            scores_by_expert.setdefault(score.user_id, []).append(score)

        for _, expert_scores in scores_by_expert.items():
            row_data: dict[str, str] = {}
            row_data["Название проекта"] = getattr(project, "name", "") if project else ""
            row_data["Фамилия эксперта"] = (
                expert_scores[0].user.last_name if expert_scores else ""
            )

            for field in program_fields:
                row_data[field.label] = field_values_map.get(field.id, "")

            scores_map: dict[int, str] = {
                score.criteria_id: score.value for score in expert_scores
            }

            for criteria in criterias_without_comment:
                row_data[criteria.name] = scores_map.get(criteria.id, "")

            if comment_criteria:
                row_data["Комментарий"] = scores_map.get(comment_criteria.id, "")

            prepared_projects_rates_data.append(row_data)

    return prepared_projects_rates_data
