import re

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django_filters import rest_framework as filters

from core.models import Specialization
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from users.utils import filter_age

User = get_user_model()
MIN_AGE_VALUE = 0
MAX_AGE_VALUE = 1000


class UserFilter(filters.FilterSet):
    """Filter for Users

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        first_name (str), last_name (str), patronymic (str),
        city (str), region (str), about_me__contains (str),
        useful_to_project__contains (str)

    Examples:
        ?first_name=test equals to .filter(first_name='test')
        ?user_type=1 equals to .filter(user_type=1)
            To check what user_types there are & what id they are, see CustomUser.VERBOSE_USER_TYPES

    """

    @classmethod
    def filter_by_partner_program(cls, queryset, name, value):
        program_id = value
        try:
            program = PartnerProgram.objects.get(pk=program_id)
            profiles_qs = (
                PartnerProgramUserProfile.objects.filter(
                    partner_program=program, user__isnull=False
                )
                .select_related("user")
                .only("user")
            )

            return queryset.filter(pk__in=[profile.user.pk for profile in profiles_qs])

        except PartnerProgram.DoesNotExist:
            return User.objects.none()

    @classmethod
    def filter_by_skills(cls, queryset, name, skills_string):
        skill_names = [
            skill.strip() for skill in skills_string.split(",") if skill.strip()
        ]

        user_content_type = ContentType.objects.get_for_model(queryset.model)

        skills_filter = Q()
        for skill_name in skill_names:
            skills_filter |= Q(
                skills__skill__name__icontains=skill_name,
                skills__content_type=user_content_type,
            )

        filtered_queryset = queryset.filter(skills_filter).distinct()

        return filtered_queryset

    @classmethod
    def filter_age__gte(cls, queryset, name, value):
        return filter_age(queryset, value, MAX_AGE_VALUE)

    @classmethod
    def filter_age__lte(cls, queryset, name, value):
        return filter_age(queryset, MIN_AGE_VALUE, value)

    @staticmethod
    def fullname_literal_pattern(value):
        """Буквальный поиск с регистром Unicode, независимый от LC_CTYPE БД.

        На существующих окружениях icontains не сворачивает регистр кириллицы.
        Явные варианты букв обходятся без изменения collation/данных; каждый
        символ экранируется, поэтому ввод пользователя не становится regex.
        """
        return "".join(
            "(?:"
            + "|".join(re.escape(v) for v in sorted({c, c.lower(), c.upper()}))
            + ")"
            for c in value
        )

    @classmethod
    def filter_by_fullname(cls, queryset, name, value):
        """Ищет фрагменты имени и фамилии совместно, также в обратном порядке.

        split нормализует пробелы; пустая строка не фильтрует. Для составных
        имён пробуем границу между двумя полями. Оба условия обязательны:
        «Иван Иванов» не должен находить Петра Иванова по одной фамилии.
        Вся фильтрация выполняется в SQL до пагинации.
        """
        words = value.split()
        if not words:
            return queryset
        # Два поля ограничены моделью. Более длинная строка не может совпасть;
        # не строим для неё большой набор SQL-условий на публичном endpoint.
        name_limit = (
            sum(
                queryset.model._meta.get_field(field).max_length
                for field in ("first_name", "last_name")
            )
            + 1
        )
        if len(" ".join(words)) > name_limit:
            return queryset.none()
        if len(words) == 1:
            pattern = cls.fullname_literal_pattern(words[0])
            return queryset.filter(
                Q(first_name__regex=pattern) | Q(last_name__regex=pattern)
            )
        predicate = Q()
        for boundary in range(1, len(words)):
            first = cls.fullname_literal_pattern(" ".join(words[:boundary]))
            last = cls.fullname_literal_pattern(" ".join(words[boundary:]))
            predicate |= (Q(first_name__regex=first) & Q(last_name__regex=last)) | (
                Q(first_name__regex=last) & Q(last_name__regex=first)
            )
        return queryset.filter(predicate)

    about_me__contains = filters.Filter(field_name="about_me", lookup_expr="contains")
    speciality__icontains = filters.Filter(
        field_name="speciality", lookup_expr="icontains"
    )
    v2_speciality = filters.NumberFilter(
        field_name="v2_speciality",
    )
    useful_to_project__contains = filters.Filter(
        field_name="useful_to_project", lookup_expr="contains"
    )
    user_type = filters.BaseInFilter(field_name="user_type", lookup_expr="in")
    partner_program = filters.NumberFilter(
        field_name="partner_program", method="filter_by_partner_program"
    )
    fullname = filters.CharFilter(method="filter_by_fullname")

    age__gte = filters.Filter(method="filter_age__gte")
    age__lte = filters.Filter(method="filter_age__lte")

    skills__contains = filters.Filter(method="filter_by_skills")

    is_mospolytech_student = filters.BooleanFilter(
        field_name="is_mospolytech_student",
        label="Студент Московского Политеха",
    )

    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "patronymic",
            "city",
            "region",
            "user_type",
            "speciality",
        )


class SpecializationFilter(filters.FilterSet):
    name__icontains = filters.Filter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = Specialization
        fields = ("name",)
