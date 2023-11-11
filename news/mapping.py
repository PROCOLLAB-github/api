from django.contrib.auth import get_user_model

from partner_programs.models import PartnerProgram
from projects.models import Project

User = get_user_model()


class NewsMapping:
    """
    Extracts title and image for news post from content_object
    """

    @classmethod
    def get_name(cls, content_object) -> str:
        if isinstance(content_object, User):
            f"{content_object.first_name} {content_object.last_name}"
        if isinstance(content_object, Project) or isinstance(
            content_object, PartnerProgram
        ):
            return content_object.name

    @classmethod
    def get_image_address(cls, content_object) -> str:
        if isinstance(content_object, User):
            return content_object.avatar
        if isinstance(content_object, Project) or isinstance(
            content_object, PartnerProgram
        ):
            return content_object.image_address
