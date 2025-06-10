import logging

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
                "Фамилия": user_program_profile.user.last_name
                if user_program_profile
                else "",
                "Имя": user_program_profile.user.first_name
                if user_program_profile
                else "",
                "Отчество": user_program_profile.user.patronymic
                if user_program_profile
                else "",
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
