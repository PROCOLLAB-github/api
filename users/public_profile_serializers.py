from rest_framework import serializers

from core.models import SkillCategory, Specialization, SpecializationCategory
from files.models import UserFile
from users.models import (
    CustomUser,
    UserAchievement,
    UserEducation,
    UserLanguages,
    UserWorkExperience,
)


class PublicProfileCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SkillCategory
        fields = ("id", "name")


class PublicProfileSpecializationCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SpecializationCategory
        fields = ("id", "name")


class PublicProfileSpecializationSerializer(serializers.ModelSerializer):
    category = PublicProfileSpecializationCategorySerializer(read_only=True)

    class Meta:
        model = Specialization
        fields = ("id", "name", "category")


class PublicProfileFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserFile
        fields = ("link", "name", "extension", "mime_type", "size")


class PublicProfileAchievementSerializer(serializers.ModelSerializer):
    files = PublicProfileFileSerializer(many=True, read_only=True)

    class Meta:
        model = UserAchievement
        fields = ("id", "title", "status", "year", "files")


class PublicProfileEducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserEducation
        fields = (
            "organization_name",
            "description",
            "entry_year",
            "completion_year",
            "education_level",
            "education_status",
        )


class PublicProfileWorkExperienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserWorkExperience
        fields = (
            "organization_name",
            "description",
            "entry_year",
            "completion_year",
            "job_position",
        )


class PublicProfileLanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserLanguages
        fields = ("language", "language_level")


class PublicProfileListSerializer(serializers.ModelSerializer):
    user_type_label = serializers.CharField(
        source="get_user_type_display", read_only=True
    )
    specialization = PublicProfileSpecializationSerializer(
        source="v2_speciality", read_only=True
    )
    skills = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        # Публичный контракт строится только через явный allow-list.
        fields = (
            "id",
            "first_name",
            "last_name",
            "avatar",
            "city",
            "user_type",
            "user_type_label",
            "specialization",
            "skills",
        )

    @staticmethod
    def get_skills(user: CustomUser) -> list[dict]:
        """Сериализует только справочные данные заранее загруженных навыков."""

        return [
            {
                "id": relation.skill_id,
                "name": relation.skill.name,
                "category": PublicProfileCategorySerializer(relation.skill.category).data,
            }
            for relation in getattr(user, "public_skills", [])
        ]


class PublicProfileDetailSerializer(PublicProfileListSerializer):
    education = PublicProfileEducationSerializer(many=True, read_only=True)
    work_experience = PublicProfileWorkExperienceSerializer(many=True, read_only=True)
    user_languages = PublicProfileLanguageSerializer(many=True, read_only=True)
    achievements = PublicProfileAchievementSerializer(many=True, read_only=True)
    social_links = serializers.SerializerMethodField()

    class Meta(PublicProfileListSerializer.Meta):
        fields = PublicProfileListSerializer.Meta.fields + (
            "patronymic",
            "about_me",
            "social_links",
            "education",
            "work_experience",
            "user_languages",
            "achievements",
        )

    @staticmethod
    def get_social_links(user: CustomUser) -> dict[str, str]:
        """Возвращает только типизированные ссылки без внутренних полей модели."""

        return {
            link.kind: link.link
            for link in getattr(user, "public_social_links", [])
            if link.kind is not None
        }
