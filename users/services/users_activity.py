from abc import ABC, abstractmethod
from enum import Enum
from typing import Any
from django.contrib.contenttypes.models import ContentType

from django.db.models import (
    Q,
    Count,
    Value,
    QuerySet,
    OuterRef,
    Subquery,
    IntegerField,
)
from django.db.models.functions import Coalesce

from users.models import CustomUser
from news.models import News
from partner_programs.models import PartnerProgramUserProfile


class ActivityPoints(Enum):
    LIKE: int = 1
    PROJECT: int = 5
    FEED_POST: int = 3
    PROFILE_FIELD: int = 1
    PROGRAM_MEMBER: int = 5
    PROGRAM_PROJECT: int = 10


class AbcstractUserActivityDataPreparer(ABC):

    @abstractmethod
    def get_users_prepared_data(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class UserActivityDataPreparer(AbcstractUserActivityDataPreparer):
    __ERROR_FIELD = "ОШИБКА"

    def get_users_prepared_data(self) -> list[dict[str, Any]]:
        """Returns list of k:v data as table row."""
        users = self.__get_user_queryset()
        return [self.__prepare_user_data(user) for user in users]

    def __prepare_user_data(self, user: CustomUser) -> dict[str, Any]:
        try:
            user_posts_count: int = user.posts_count if user.posts_count is not None else 0
            user_projects_in_program: int = user.projects_in_program if user.projects_in_program is not None else 0
            user_programs: str = ", ".join(
                [program.partner_program.name for program in user.partner_program_profiles.all()]
            )

            user_data = {
                "ID пользователя": user.id,
                "Имя и фамилия": user.get_full_name(),
                "Возраст": user.get_user_age(),
                "Баллы за профиль": self.__get_profile_points(user=user),
                "Кол-во лайков": user.likes_count,
                "Баллы за лайки": user.likes_count * ActivityPoints.LIKE.value,
                "Кол-во новостей": user_posts_count,
                "Баллы за новости": user_posts_count * ActivityPoints.FEED_POST.value,
                "Кол-во проектов": user.projects_count,
                "Баллы за проекты": user.projects_count * ActivityPoints.PROJECT.value,
                "Участие в программах кол-во": user.program_profiles_count,
                "Программы": user_programs,
                "Баллы за программы": user.program_profiles_count * ActivityPoints.PROGRAM_MEMBER.value,
                "Кол-во проектов в программе": user_projects_in_program,
                "Баллы за проекты в программе": user_projects_in_program * ActivityPoints.PROGRAM_PROJECT.value,
            }
            user_data["Cумма баллов"] = sum((user_data[key] for key in user_data if key.startswith("Баллы ")))
            return user_data
        except Exception:
            user_data = {
                "ID пользователя": self.__ERROR_FIELD,
                "Имя и фамилия": self.__ERROR_FIELD,
                "Возраст": self.__ERROR_FIELD,
                "Баллы за профиль": self.__ERROR_FIELD,
                "Кол-во лайков": self.__ERROR_FIELD,
                "Баллы за лайки": self.__ERROR_FIELD,
                "Кол-во новостей": self.__ERROR_FIELD,
                "Баллы за новости": self.__ERROR_FIELD,
                "Кол-во проектов": self.__ERROR_FIELD,
                "Баллы за проекты": self.__ERROR_FIELD,
                "Участие в программах кол-во": self.__ERROR_FIELD,
                "Программы": self.__ERROR_FIELD,
                "Баллы за программы": self.__ERROR_FIELD,
                "Кол-во проектов в программе": self.__ERROR_FIELD,
                "Баллы за проекты в программе": self.__ERROR_FIELD,
                "Cумма баллов": self.__ERROR_FIELD,
            }
            return user_data

    def __get_user_queryset(self) -> QuerySet[CustomUser]:
        user_content_type = ContentType.objects.get_for_model(CustomUser)
        projects_in_program_subquery = (
            PartnerProgramUserProfile.objects
            .filter(user_id=OuterRef("id"))
            .exclude(project=None)
            .values("user_id")
            .annotate(total=Count("id"))
            .values("total")
        )
        posts_count_subquery = (
            News.objects
            .filter(content_type=user_content_type, object_id=OuterRef("id"))
            .values("object_id")
            .annotate(total=Count("id"))
            .values("total")
        )
        likes_count_subquery = (
            CustomUser.objects
            .filter(likes__user_id=OuterRef("id"))
            .annotate(total_likes=Count("likes"))
            .values("total_likes")
        )

        projects_in_program_subquery = (
            CustomUser.objects
            .filter(partner_program_profiles__user_id=OuterRef("id"))
            .annotate(total_proj=Count("id"))
            .values("total_proj")
        )

        users: QuerySet[CustomUser] = (
            CustomUser.objects
            .prefetch_related(
                "likes",
                "education",
                "skills",
                "v2_speciality",
                "work_experience",
                "user_languages",
                "partner_program_profiles__partner_program",
            )
            .annotate(
                projects_count=Count("leaders_projects"),
                likes_count=Coalesce(
                    Subquery(likes_count_subquery, output_field=IntegerField()),
                    Value(0),
                    output_field=IntegerField(),
                ),
                program_profiles_count=Coalesce(
                    Subquery(projects_in_program_subquery, output_field=IntegerField()),
                    Value(0),
                    output_field=IntegerField(),
                ),
                projects_in_program=Coalesce(
                    Subquery(projects_in_program_subquery, output_field=IntegerField()),
                    Value(0),
                    output_field=IntegerField(),
                ),
                posts_count=Coalesce(
                    Subquery(posts_count_subquery, output_field=IntegerField()),
                    Value(0),
                    output_field=IntegerField(),
                ),
            )
        )
        return users

    def __get_profile_points(self, user: CustomUser) -> int:
        """Checks availability profile fields for aditional points."""
        education: bool | int = user.education.exists() if user.education else 0
        work_experience: bool | int = user.work_experience.exists() if user.work_experience else 0
        user_languages: bool | int = user.user_languages.exists() if user.user_languages else 0
        skills: bool | int = user.skills.exists() if user.skills else 0
        v2_speciality: bool = bool(user.v2_speciality)
        return education + work_experience + user_languages + skills + v2_speciality
