import logging
import io
from collections import OrderedDict
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Prefetch
from django.utils import timezone
from openpyxl import Workbook
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.utils import XlsxFileToExport, sanitize_excel_value
from partner_programs.helpers import date_to_iso
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from project_rates.models import Criteria, ProjectScore
from projects.models import Collaborator, Project
from vacancy.mapping import MessageTypeEnum, UserProgramRegisterParams
from vacancy.tasks import send_email

logger = logging.getLogger()
User = get_user_model()

EXTERNAL_REGISTRATION_USER_FIELDS = (
    "first_name",
    "last_name",
    "patronymic",
    "city",
)


class ProgramRegistrationError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class ProgramProjectAlreadyApplied(Exception):
    def __init__(self, program_link: PartnerProgramProject):
        self.program_link = program_link
        super().__init__("Проект уже подан в эту программу.")


class ProgramProjectFilterError(Exception):
    def __init__(self, detail: dict):
        self.detail = detail
        super().__init__(str(detail))


@dataclass(frozen=True)
class ProgramProjectApplicationResult:
    project: Project
    program_link: PartnerProgramProject


@dataclass(frozen=True)
class ProgramExportFile:
    binary_data: bytes
    base_name: str


def _send_program_registration_email(user, program: PartnerProgram) -> None:
    send_email.delay(
        UserProgramRegisterParams(
            message_type=MessageTypeEnum.REGISTERED_PROGRAM_USER.value,
            user_id=user.id,
            program_name=program.name,
            program_id=program.id,
            schema_id=2,
        )
    )


def register_user_to_program(
    *,
    program: PartnerProgram,
    user: User,
    data,
) -> PartnerProgramUserProfile:
    if program.datetime_registration_ends < timezone.now():
        raise ProgramRegistrationError("Registration period has ended.")

    try:
        user_profile = PartnerProgramUserProfile.objects.create(
            partner_program_data=data,
            user=user,
            partner_program=program,
        )
    except IntegrityError:
        raise ProgramRegistrationError("User already registered to this program.")

    _send_program_registration_email(user, program)
    return user_profile


def create_user_and_register_to_program(
    *,
    program: PartnerProgram,
    data,
) -> PartnerProgramUserProfile:
    email = data.get("email") if data.get("email") else data.get("email_")
    if not email:
        raise ProgramRegistrationError("You need to pass an email address.")

    password = data.get("password")
    if not password:
        raise ProgramRegistrationError("You need to pass a password.")

    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "birthday": date_to_iso(data.get("birthday", "01-01-1900")),
            "is_active": True,  # bypass email verification for external forms
            "onboarding_stage": None,  # bypass onboarding for external forms
            "verification_date": timezone.now(),  # bypass manual verification
            **{
                field_name: data.get(field_name, "")
                for field_name in EXTERNAL_REGISTRATION_USER_FIELDS
            },
        },
    )
    if created:
        user.set_password(password)
        user.save()

    user_profile_program_data = {
        k: v
        for k, v in data.items()
        if k not in EXTERNAL_REGISTRATION_USER_FIELDS and k != "password"
    }
    try:
        user_profile = PartnerProgramUserProfile.objects.create(
            partner_program_data=user_profile_program_data,
            user=user,
            partner_program=program,
        )
    except IntegrityError:
        raise ProgramRegistrationError(
            "User has already registered in this program."
        )

    _send_program_registration_email(user, program)
    return user_profile


def require_can_apply_project_to_program(
    *,
    program: PartnerProgram,
    user: User,
) -> None:
    if not program.is_project_submission_open():
        raise ValidationError("Срок подачи проектов в программу завершён.")

    if program.is_manager(user):
        return

    if not PartnerProgramUserProfile.objects.filter(
        user=user,
        partner_program=program,
    ).exists():
        raise PermissionDenied("Подача проекта доступна только участникам программы.")


def _validate_unique_program_fields(values_data: list[dict]) -> None:
    seen_field_ids: set[int] = set()
    duplicate_ids: set[int] = set()
    for item in values_data:
        field_id = item["field"].id
        if field_id in seen_field_ids:
            duplicate_ids.add(field_id)
        seen_field_ids.add(field_id)
    if duplicate_ids:
        raise ValidationError(
            {"program_field_values": f"Есть повторяющиеся field_id: {sorted(duplicate_ids)}"}
        )


def _validate_required_program_fields(
    *,
    program: PartnerProgram,
    values_data: list[dict],
) -> None:
    required_fields = list(
        program.fields.filter(is_required=True).values("id", "label")
    )
    provided_field_ids = {item["field"].id for item in values_data}
    missing_required = [
        field["label"]
        for field in required_fields
        if field["id"] not in provided_field_ids
    ]
    if missing_required:
        raise ValidationError(
            {"program_field_values": f"Не заполнены обязательные поля: {missing_required}"}
        )


def _validate_program_field_ownership(
    *,
    program: PartnerProgram,
    values_data: list[dict],
) -> None:
    for item in values_data:
        field = item["field"]
        if field.partner_program_id != program.id:
            raise ValidationError(
                {
                    "program_field_values": f"Поле id={field.id} не относится к этой программе."
                }
            )


def apply_project_to_program(
    *,
    program: PartnerProgram,
    user: User,
    data,
    serializer_class,
) -> ProgramProjectApplicationResult:
    require_can_apply_project_to_program(program=program, user=user)

    existing_link = (
        PartnerProgramProject.objects.select_related("project")
        .filter(partner_program=program, project__leader=user)
        .first()
    )
    if existing_link:
        raise ProgramProjectAlreadyApplied(existing_link)

    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data

    project_data = validated_data["project"]
    values_data = validated_data.get("program_field_values") or []

    _validate_unique_program_fields(values_data)
    _validate_required_program_fields(program=program, values_data=values_data)
    _validate_program_field_ownership(program=program, values_data=values_data)

    with transaction.atomic():
        project = Project.objects.create(
            leader=user,
            draft=True,
            is_public=False,
            **project_data,
        )
        program_link = PartnerProgramProject.objects.create(
            partner_program=program,
            project=project,
        )

        profile = PartnerProgramUserProfile.objects.filter(
            user=user,
            partner_program=program,
        ).first()
        if profile:
            profile.project = project
            profile.save(update_fields=["project"])

        value_objs = [
            PartnerProgramFieldValue(
                program_project=program_link,
                field=item["field"],
                value_text=item.get("value_text") or "",
            )
            for item in values_data
        ]
        if value_objs:
            PartnerProgramFieldValue.objects.bulk_create(value_objs)

    return ProgramProjectApplicationResult(project=project, program_link=program_link)


def get_filterable_program_fields(program: PartnerProgram):
    return PartnerProgramField.objects.filter(
        partner_program=program,
        show_filter=True,
    )


def validate_program_project_filters(
    *,
    program: PartnerProgram,
    filters: dict[str, list[str]],
) -> None:
    field_names = list(filters.keys())
    field_qs = PartnerProgramField.objects.filter(
        partner_program=program,
        name__in=field_names,
    )
    field_by_name = {field.name: field for field in field_qs}

    missing = [name for name in field_names if name not in field_by_name]
    if missing:
        raise ProgramProjectFilterError(
            {"detail": f"Поля не найденные в программе: {missing}"}
        )

    for field_name, values in filters.items():
        field_obj = field_by_name[field_name]
        if not field_obj.show_filter:
            raise ProgramProjectFilterError(
                {
                    "detail": (
                        f"Поле '{field_name}' недоступно для фильтрации "
                        "(show_filter=False)."
                    )
                }
            )

        options = field_obj.get_options_list()
        if not options:
            raise ProgramProjectFilterError(
                {"detail": f"Поле '{field_name}' не имеет вариантов (options)."}
            )

        invalid_values = [value for value in values if value not in options]
        if invalid_values:
            raise ProgramProjectFilterError(
                {
                    "detail": f"Неверные значения для поля '{field_name}'.",
                    "invalid": invalid_values,
                }
            )


def get_filtered_program_project_links(
    *,
    program: PartnerProgram,
    filters: dict[str, list[str]],
):
    validate_program_project_filters(program=program, filters=filters)

    qs = PartnerProgramProject.objects.filter(partner_program=program)
    if not filters:
        return qs.select_related("project").distinct()

    for field_name, values in filters.items():
        field = PartnerProgramField.objects.get(
            partner_program=program,
            name=field_name.strip(),
        )
        field_value_exists = PartnerProgramFieldValue.objects.filter(
            program_project=OuterRef("pk"),
            field=field,
            value_text__in=values,
        )
        qs = qs.filter(Exists(field_value_exists))

    return qs.select_related("project").distinct()


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
    prefetched_collaborators = getattr(project, "_prefetched_collaborators", None)
    if prefetched_collaborators is not None:
        return 1 + len(prefetched_collaborators)

    try:
        if hasattr(project, "get_collaborators_user_list"):
            return 1 + len(project.get_collaborators_user_list())
        if hasattr(project, "collaborator_set"):
            return 1 + project.collaborator_set.count()
    except Exception:
        pass
    return 1


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


def build_program_projects_export_file(
    *,
    program: PartnerProgram,
    only_submitted: bool,
) -> ProgramExportFile:
    extra_cols = build_program_field_columns(program)
    header_pairs = BASE_COLUMNS + extra_cols

    field_values_qs = PartnerProgramFieldValue.objects.select_related("field").filter(
        field__partner_program_id=program.id
    )
    links_qs = program.program_projects.select_related(
        "project",
        "project__leader",
    ).prefetch_related(
        Prefetch(
            "field_values",
            queryset=field_values_qs,
            to_attr="_prefetched_field_values",
        ),
        Prefetch(
            "project__collaborator_set",
            queryset=Collaborator.objects.select_related("user"),
            to_attr="_prefetched_collaborators",
        ),
    )
    if only_submitted:
        links_qs = links_qs.filter(submitted=True)

    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet(title="Проекты")
    worksheet.append([title for _, title in header_pairs])

    extra_keys_order = [key for key, _ in extra_cols]
    for row_number, program_project_link in enumerate(links_qs, start=1):
        row_dict = row_dict_for_link(
            program_project_link=program_project_link,
            extra_field_keys_order=extra_keys_order,
            row_number=row_number,
        )
        raw_values = [row_dict.get(key, "") for key, _ in header_pairs]
        worksheet.append([sanitize_excel_value(value) for value in raw_values])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    label = "projects_review" if only_submitted else "projects"
    date_suffix = timezone.now().strftime("%d.%m.%y")
    base_name = f"{label} - {program.name or 'program'} - {date_suffix}"
    return ProgramExportFile(binary_data=buffer.getvalue(), base_name=base_name)


def build_program_project_scores_export_file(
    *,
    program: PartnerProgram,
) -> ProgramExportFile:
    rates_data_to_write = prepare_project_scores_export_data(program.id)
    xlsx_file_writer = XlsxFileToExport()
    xlsx_file_writer.write_data_to_xlsx(rates_data_to_write)
    binary_data_to_export: bytes = xlsx_file_writer.get_binary_data_from_self_file()
    xlsx_file_writer.clear_buffer()

    date_suffix = timezone.now().strftime("%d.%m.%y")
    base_name = f"scores - {program.name or 'program'} - {date_suffix}"
    return ProgramExportFile(
        binary_data=binary_data_to_export,
        base_name=base_name,
    )


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
            row_data["Название проекта"] = (
                getattr(project, "name", "") if project else ""
            )
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
