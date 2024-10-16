from django.db.models import Count
from django_filters import rest_framework as filters

from users.models import Expert
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from projects.models import Project
from project_rates.models import ProjectScore


class ProjectFilter(filters.FilterSet):
    """Filter for Projects

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        industry (int), step (int), region (str), name__contains (str),
         description__contains (str), collaborator__user__in (List[int]),
         datetime_created__gt (datetime.datetime), step (int), any_vacancies (bool),
         member_count__gt (int), member_count__lt (int), leader (int), partner_program (int),
         is_company (bool).

    Examples:
        ?industry=1&name__contains=clown
            equals to .filter(industry=1, name__contains='clown')
        ?datetime_created__gt=25.10.2022
            equals to .filter(datetime_created__gt=datetime.datetime(...))
        ?collaborator__user__in=1,2 equals to .filter(collaborator__user__in=[1, 2])
        ?step=1 equals to .filter(step=1)
        ?any_vacancies=true equals to .filter(any_vacancies=True)
        ?collaborator__count__gt=1 equals to .filter(collaborator__count__gt=1)
        ?is_company=0/?is_company=false equals .filter(is_company=False)
    """

    @classmethod
    def filter_collaborator_count_lte(cls, queryset, name, value):
        return queryset.alias(Count("collaborator")).filter(
            collaborator__count__lte=value
        )

    @classmethod
    def filter_collaborator_count_gte(cls, queryset, name, value):
        return queryset.alias(Count("collaborator")).filter(
            collaborator__count__gte=value
        )

    @classmethod
    def vacancy_filter(cls, queryset, name, value):
        """Filter by vacancies
        If value is False, returns all projects.
        If value is True, returns projects with active vacancies.
        """
        if value:
            return queryset.filter(
                vacancies__is_active=True, vacancies__isnull=False
            ).distinct()
        return queryset

    def filter_by_partner_program(self, queryset, name, value):
        program_id = value

        user = self.request.user
        try:
            program = PartnerProgram.objects.get(pk=program_id)
            program_status = program.projects_availability
            # If available to all users or request.user is an expert of this program.
            if (
                program_status == "all_users"
                or Expert.objects.filter(user=user, programs=program).exists()
            ):
                profiles_qs = (
                    PartnerProgramUserProfile.objects.filter(
                        partner_program=program, project__isnull=False
                    )
                    .select_related("project")
                    .only("project")
                )
                return queryset.filter(
                    pk__in=[profile.project.pk for profile in profiles_qs]
                )
            else:
                return Project.objects.none()

        except PartnerProgram.DoesNotExist:
            return Project.objects.none()

    def filter_by_have_expert_rates(self, queryset, name, value):
        rated_projects_ids = ProjectScore.objects.values_list(
            "project_id", flat=True
        ).distinct()
        if value:
            return queryset.filter(id__in=rated_projects_ids)
        return queryset.exclude(id__in=rated_projects_ids)

    name__contains = filters.Filter(field_name="name", lookup_expr="contains")
    description__contains = filters.Filter(
        field_name="description", lookup_expr="contains"
    )
    collaborator__user__in = filters.BaseInFilter(
        field_name="collaborator__user", lookup_expr="in"
    )
    datetime_created__gt = filters.DateTimeFilter(
        field_name="datetime_created", lookup_expr="gt"
    )
    is_company = filters.BooleanFilter(
        field_name="is_company",
        label="is_company\n`1`/`true` is company\n`0`/`false` is not company",
    )

    # filters by whether there are any vacancies in the project
    any_vacancies = filters.BooleanFilter(field_name="vacancies", method="vacancy_filter")
    collaborator__count__gte = filters.NumberFilter(
        field_name="collaborator", method="filter_collaborator_count_gte"
    )
    collaborator__count__lte = filters.NumberFilter(
        field_name="collaborator", method="filter_collaborator_count_lte"
    )
    step = filters.NumberFilter(field_name="step")
    partner_program = filters.NumberFilter(
        field_name="partner_program", method="filter_by_partner_program"
    )
    is_rated_by_expert = filters.BooleanFilter(
        method="filter_by_have_expert_rates",
        label=("is_rated_by_expert\n`1`/`true` rated projects\n`0`/`false` dosn't rated"),
    )

    class Meta:
        model = Project
        fields = (
            "industry",
            "step",
            "region",
            "leader",
            "step",
            "partner_program",
            "is_company",
        )
