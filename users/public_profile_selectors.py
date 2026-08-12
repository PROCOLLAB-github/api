from django.contrib.contenttypes.models import ContentType
from django.db.models import Prefetch, QuerySet

from core.models import SkillToObject
from users.models import (
    CustomUser,
    UserAchievement,
    UserEducation,
    UserLanguages,
    UserLink,
    UserWorkExperience,
)


def get_public_profiles_queryset(*, detailed: bool = False) -> QuerySet[CustomUser]:
    """Возвращает активные профили с данными, разрешёнными публичным контрактом."""

    user_content_type = ContentType.objects.get_for_model(CustomUser)
    skills = (
        SkillToObject.objects.filter(content_type=user_content_type)
        .select_related("skill", "skill__category")
        .order_by("skill__name", "skill_id")
    )

    queryset = (
        CustomUser.objects.filter(is_active=True)
        .select_related("v2_speciality", "v2_speciality__category")
        .prefetch_related(Prefetch("skills", queryset=skills, to_attr="public_skills"))
    )

    if detailed:
        queryset = queryset.prefetch_related(
            Prefetch(
                "links",
                queryset=UserLink.objects.filter(kind__isnull=False).order_by("kind"),
                to_attr="public_social_links",
            ),
            Prefetch("education", queryset=UserEducation.objects.order_by("id")),
            Prefetch(
                "work_experience",
                queryset=UserWorkExperience.objects.order_by("id"),
            ),
            Prefetch("user_languages", queryset=UserLanguages.objects.order_by("id")),
            Prefetch(
                "achievements",
                queryset=UserAchievement.objects.order_by("id").prefetch_related("files"),
            ),
        )

    return queryset.distinct().order_by("first_name", "last_name", "id")
