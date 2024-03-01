from django.db.models import QuerySet, Count, Q

from project_rates.models import Criteria, ProjectScore
from project_rates.serializers import (
    CriteriaSerializer,
    ProjectScoreSerializer,
    ProjectScoreGetSerializer,
)
from projects.models import Project


def get_querysets(**kwargs) -> dict[str, QuerySet]:
    """
    Kwargs arguments input:

    program_id: int,
    user: CustomUser,
    view: ListAPIView,
    scored: bool = False,
    project_id: int | None = None,

    """
    program_id = kwargs.get("program_id")
    user = kwargs.get("user")

    criterias = Criteria.objects.prefetch_related("partner_program").filter(
        partner_program_id=program_id
    )
    scores = ProjectScore.objects.prefetch_related("criteria").filter(
        criteria__in=criterias.values_list("id", flat=True), user=user
    )

    unpaginated_projects = Project.objects.filter(
        partner_program_profiles__partner_program_id=program_id
    ).distinct()

    if kwargs.get("scored"):
        quantity_criterias = len(criterias)
        unpaginated_projects = unpaginated_projects.annotate(
            user_scores_count=Count("scores", filter=Q(scores__user=user))
        ).filter(user_scores_count=quantity_criterias)
    elif kwargs.get("project_id"):
        unpaginated_projects = unpaginated_projects.filter(id=kwargs.get("project_id"))

    paginated_projects = kwargs.get("view").paginate_queryset(unpaginated_projects)

    return {
        "criterias_queryset": criterias,
        "scores_queryset": scores,
        "paginated_projects_queryset": paginated_projects,
    }


def serialize_project_criterias(querysets: dict[str, QuerySet]) -> list[dict]:
    criteria_serializer = CriteriaSerializer(querysets["criterias_queryset"], many=True)
    scores_serializer = ProjectScoreSerializer(querysets["scores_queryset"], many=True)

    projects_serializer = ProjectScoreGetSerializer(
        querysets["paginated_projects_queryset"],
        context={
            "data_criterias": criteria_serializer.data,
            "data_scores": scores_serializer.data,
        },
        many=True,
    )
    return projects_serializer.data


def count_scored_criterias(project_data: dict) -> None:
    filled_values = sum(
        1
        for criteria in project_data["criterias"]
        if criteria["name"] == "Комментарий" or criteria.get("value")
    )

    if filled_values == len(project_data["criterias"]):
        project_data["is_scored"] = True
