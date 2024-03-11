from django.db.models import Count, Q

from project_rates.constants import RatesQuerySets
from project_rates.models import Criteria, ProjectScore
from project_rates.serializers import (
    CriteriaSerializer,
    ProjectScoreSerializer,
    ProjectScoreGetSerializer,
)
from projects.models import Project


def get_querysets(RatesRequestData) -> RatesQuerySets:
    program_id = RatesRequestData.program_id
    project_id = RatesRequestData.project_id
    user = RatesRequestData.user

    criterias = Criteria.objects.prefetch_related("partner_program").filter(
        partner_program_id=program_id
    )
    scores = ProjectScore.objects.prefetch_related("criteria").filter(
        criteria__in=criterias.values_list("id", flat=True), user=user
    )

    if project_id:
        projects = [Project.objects.get(id=project_id)]
    else:
        projects = Project.objects.filter(
            partner_program_profiles__partner_program_id=program_id
        ).distinct()

    if RatesRequestData.scored:
        criterias_quantity = len(criterias)
        projects = projects.annotate(
            user_scores_count=Count("scores", filter=Q(scores__user=user))
        ).filter(user_scores_count=criterias_quantity)

    if not project_id:
        projects = RatesRequestData.view.paginate_queryset(projects)

    return RatesQuerySets(
        criterias_queryset=criterias, scores_queryset=scores, projects_queryset=projects
    )


def serialize_project_criterias(querysets: RatesQuerySets) -> list[dict]:
    criteria_serializer = CriteriaSerializer(querysets.criterias_queryset, many=True)
    scores_serializer = ProjectScoreSerializer(querysets.scores_queryset, many=True)

    projects_serializer = ProjectScoreGetSerializer(
        querysets.projects_queryset,
        context={
            "data_criterias": criteria_serializer.data,
            "data_scores": scores_serializer.data,
        },
        many=True,
    )
    return projects_serializer.data


def count_scored_criterias(project_data: dict):
    filled_values = sum(
        1
        for criteria in project_data["criterias"]
        if criteria["name"] == "Комментарий" or criteria.get("value")
    )

    if filled_values == len(project_data["criterias"]):
        project_data["is_scored"] = True
