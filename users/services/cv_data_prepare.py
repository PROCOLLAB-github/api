import os
from datetime import date

from django.conf import settings
from django.db.models import Count, Prefetch
from django.contrib.auth import get_user_model

from core.models import SkillToObject
from core.services import Base64ImageEncoder
from partner_programs.models import PartnerProgramUserProfile
from users.typing import UserCVData
from users.models import (
    CustomUser,
    UserAchievement,
    UserEducation,
    UserLink,
)


User = get_user_model()


class UserCVDataPreparer:
    __ASSETS_LOCAL_PATH = os.path.join(settings.BASE_DIR, *["assets", "users", "user_CV"])
    # Links:
    __PROCOLLAB_USER_PATH = "https://app.procollab.ru/office/profile/"
    # Images:
    __PROCOLLAB_LOGO_FILENAME = "procollab.svg"
    __IC_LOCATION_FILENAME = "ic_location.svg"
    __IC_PROFILE_FILENAME = "ic_profile.svg"
    __INFINITY_GRADIENT_FILENAME = "infinity_gradient.svg"
    __EMPTY_USER_AVATAR_FILENAME = "avatar-placeholder.jpg"
    # Fonts:
    __FONT_SEMIBOLD_FILENAME = "Mont-SemiBold.ttf"
    __FONT_HEAVY_FILENAME = "Mont-Heavy.ttf"
    __FONT_EXTRALIGHT_FILENAME = "Mont-ExtraLight.ttf"
    __FONT_REGULAR_FILENAME = "Mont-Regular.ttf"

    def __init__(self, user_pk: int) -> None:
        self.user_pk = user_pk

    def get_prepared_data(self) -> UserCVData:
        """
        UserCV have 4 types of fields:
            base_info: No need to prepare data.
            complex_data: Example(age, skills_to_obj).
            images: Needs to be converted to base64 for rendering.
            fonts: Absolute path must be obtained before using in PDF.
        """
        user_instance: CustomUser = self._get_user_instance()
        user_data: UserCVData = {
            # base_info:
            "base_user_info": user_instance,
            "position": user_instance.v2_speciality.name if user_instance.v2_speciality else user_instance.speciality,
            "user_link_from_procollab": f"{self.__PROCOLLAB_USER_PATH}{user_instance.pk}",
            # complex_data:
            "user_age": self._get_user_age(user_instance),
            "skills_to_obj": user_instance.skills.all(),
            "experience": user_instance.education.all(),
            "achievements": user_instance.achievements.all(),
            "user_contacts": user_instance.links.all(),
            "user_programs": user_instance.partner_program_profiles.all(),
            # images:
            "user_avatar": self._get_encoded_user_avatar(user_instance),
            "procollab_logo": self._get_encoded_image_from_local_path(self.__PROCOLLAB_LOGO_FILENAME),
            "ic_location": self._get_encoded_image_from_local_path(self.__IC_LOCATION_FILENAME),
            "encoded_ic_profile": self._get_encoded_image_from_local_path(self.__IC_PROFILE_FILENAME),
            "infinity_gradient": self._get_encoded_image_from_local_path(self.__INFINITY_GRADIENT_FILENAME),
            # Fonts:
            "fonts": self._get_fonts_absolute_paths_for_render(),
        }
        return user_data

    def _get_user_instance(self) -> CustomUser:
        user = (
            User.objects.select_related("v2_speciality")
            .prefetch_related(
                Prefetch("education", queryset=UserEducation.objects.all()),
                Prefetch("achievements", queryset=UserAchievement.objects.all()),
                Prefetch("links", queryset=UserLink.objects.all()),
                Prefetch(
                    "skills",
                    queryset=(
                        SkillToObject.objects
                        .select_related("skill")
                        .annotate(approuve_count=Count("confirmations"))
                    )
                ),
                Prefetch(
                    "partner_program_profiles",
                    queryset=PartnerProgramUserProfile.objects.select_related("partner_program"))
            )
            .get(pk=self.user_pk)
        )
        return user

    def _get_user_age(self, user_instance: CustomUser) -> int:
        today = date.today()
        birthday = user_instance.birthday
        if birthday:
            return today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
        return None

    def _get_encoded_image_from_local_path(self, path_to_image: str) -> str:
        """Local files also need to be converted to base64 for rendering."""
        os_image_path: str = self._get_os_file_path(path_to_image)
        encoded_image = Base64ImageEncoder().get_encoded_base64_from_local_path(os_image_path)
        return encoded_image

    def _get_encoded_user_avatar(self, user_instance: CustomUser) -> str:
        """
        Prepare user avatar for render (base64).
        If user dont have avatar, take local `avatar-placeholder`.
        """
        if user_instance.avatar:
            encoded_base64_avatar: str = Base64ImageEncoder().get_encoded_base64_from_url(user_instance.avatar)
        else:
            user_avatar_placeholder_path: str = self._get_os_file_path(self.__EMPTY_USER_AVATAR_FILENAME)
            encoded_base64_avatar: str = self._get_encoded_image_from_local_path(user_avatar_placeholder_path)
        return encoded_base64_avatar

    def _get_fonts_absolute_paths_for_render(self) -> dict[str, str]:
        """Prepare absolute paths for fonts (needs for correct render)."""
        fonts: dict[str, str] = {
            "font_semibold_path": self._get_os_file_path(self.__FONT_SEMIBOLD_FILENAME).replace("\\", "/"),
            "font_heavy_path": self._get_os_file_path(self.__FONT_HEAVY_FILENAME).replace("\\", "/"),
            "font_extralight_path": self._get_os_file_path(self.__FONT_EXTRALIGHT_FILENAME).replace("\\", "/"),
            "font_regular_path": self._get_os_file_path(self.__FONT_REGULAR_FILENAME).replace("\\", "/"),
        }
        return fonts

    def _get_os_file_path(self, file_path: str) -> str:
        """Prepare absolute filepath."""
        return os.path.join(self.__ASSETS_LOCAL_PATH, file_path)
