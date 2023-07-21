from django.contrib.auth import get_user_model
from django_filters import rest_framework as filters

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile

User = get_user_model()


class UserFilter(filters.FilterSet):
    """Filter for Users

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        first_name (str), last_name (str), patronymic (str),
        city (str), region (str), organization (str), about_me__contains (str),
        key_skills__contains (str), useful_to_project__contains (str)

    Examples:
        ?first_name=test equals to .filter(first_name='test')
        ?key_skills__contains=yawning equals to .filter(key_skills__containing='yawning')
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
                .all()
            )

            return queryset.filter(pk__in=[profile.user.pk for profile in profiles_qs])

        except PartnerProgram.DoesNotExist:
            return User.objects.none()

    about_me__contains = filters.Filter(field_name="about_me", lookup_expr="contains")
    key_skills__contains = filters.Filter(field_name="key_skills", lookup_expr="contains")
    useful_to_project__contains = filters.Filter(
        field_name="useful_to_project", lookup_expr="contains"
    )
    user_type = filters.BaseInFilter(field_name="user_type", lookup_expr="in")
    partner_program = filters.NumberFilter(
        field_name="partner_program", method="filter_by_partner_program"
    )

    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "patronymic",
            "city",
            "region",
            "organization",
            "user_type",
        )
