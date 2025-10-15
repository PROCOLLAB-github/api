import logging
from collections import OrderedDict

from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from partner_programs.models import PartnerProgramUserProfile
from project_rates.models import Criteria, ProjectScore

logger = logging.getLogger()


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
    ("leader_full_name", "Имя фамилия лидера"),
]
EXCEL_CELL_MAX = 32767  # лимит символов в ячейке Excel


def sanitize_excel_value(value):
    """
    Приводит значение к безопасному для openpyxl виду:
    - None -> ""
    - для строк: вычищает запрещённые символы, нормализует переносы строк,
      и обрезает до лимита Excel (32767).
    - для чисел/булевых оставляет как есть.
    """
    if value is None:
        return ""

    if isinstance(value, (int, float, bool)):
        return value

    text = str(value)
    # нормализуем переносы (на всякий случай)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # выкидываем запрещённые символы (в т.ч. \x0B)
    text = ILLEGAL_CHARACTERS_RE.sub(" ", text)

    # Excel не примет строки длиннее 32767
    if len(text) > EXCEL_CELL_MAX:
        text = text[: EXCEL_CELL_MAX - 3] + "..."

    return text


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
    try:
        if hasattr(project, "get_collaborators_user_list"):
            return 1 + len(project.get_collaborators_user_list())
        if hasattr(project, "collaborator_set"):
            return 1 + project.collaborator_set.count()
    except Exception:
        pass
    return 1


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
