from typing import TypedDict

from django.db.models import QuerySet

from users.models import (
    CustomUser,
    UserEducation,
    UserWorkExperience,
    UserLanguages,
)
from core.models import SkillToObject


class UserCVDataV2(TypedDict):
    """Typed dict.
    Params:
        - base_user_info: CustomUser -> Simple user info from user instance.
        - position: str -> Position (user have 2 fields for this).
        - user_age: str -> Age need to be prepared before render.
        - skills_to_obj: QuerySet[SkillToObject] -> User skills.
        - education: QuerySet[UserEducation] -> User education experience.
        - work_experience: QuerySet[UserWorkExperience] -> User work experience.
        - user_languages: QuerySet[UserLanguages] -> User languages knowledges.
        - user_avatar: str -> Image need to be prepared(base64) before render.
        - procollab_logo: str -> Image need to be prepared(base64) before render.
        - fonts: dict[str, str] -> Absolute paths to fonts.
    """

    base_user_info: CustomUser
    position: str
    user_age: str | None
    skills_to_obj: QuerySet[SkillToObject]
    education: QuerySet[UserEducation]
    work_experience: QuerySet[UserWorkExperience]
    user_languages: QuerySet[UserLanguages]
    user_avatar: str
    procollab_logo: str
    fonts: dict[str, str]
