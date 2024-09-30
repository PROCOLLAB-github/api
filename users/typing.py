from typing import TypedDict

from django.db.models import QuerySet

from users.models import (
    CustomUser,
    UserAchievement,
    UserEducation,
    UserLink,
)
from partner_programs.models import PartnerProgramUserProfile
from core.models import SkillToObject


class UserCVData(TypedDict):
    """Typed dict.
    Params:
        - base_user_info: CustomUser -> Simple user info from user instance.
        - position: str -> Position (user have 2 fields for this).
        - user_age: int -> Age need to be prepared before render.
        - user_link_from_procollab: str -> Procollab link + user.id.
        - skills_to_obj: QuerySet[SkillToObject] -> User skills.
        - experience: QuerySet[UserEducation] -> User experience.
        - achievements: QuerySet[UserAchievement] -> User achievements.
        - user_contacts: QuerySet[UserLink] -> User contacts.
        - user_programs: QuerySet[PartnerProgramUserProfile] -> User programs.
        - user_avatar: str -> Image need to be prepared(base64) before render.
        - procollab_logo: str -> Image need to be prepared(base64) before render.
        - ic_location: str -> Image need to be prepared(base64) before render.
        - encoded_ic_profile: str -> Image need to be prepared(base64) before render.
        - infinity_gradient: str -> Image need to be prepared(base64) before render.
        - fonts: dict[str, str] -> Absolute paths to fonts.
    """

    base_user_info: CustomUser
    position: str
    user_age: int
    skills_to_obj: QuerySet[SkillToObject]
    experience: QuerySet[UserEducation]
    achievements: QuerySet[UserAchievement]
    user_contacts: QuerySet[UserLink]
    user_programs: QuerySet[PartnerProgramUserProfile]
    user_link_from_procollab: str
    user_avatar: str
    procollab_logo: str
    ic_location: str
    encoded_ic_profile: str
    infinity_gradient: str
    fonts: dict[str, str]
