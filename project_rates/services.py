from django.db import transaction
from django.db.models import Count, Prefetch, Q, QuerySet
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from partner_programs.models import PartnerProgram, PartnerProgramProject
from partner_programs.serializers import ProgramProjectFilterRequestSerializer
from partner_programs.utils import filter_program_projects_by_field_name
from projects.models import Project
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from project_rates.serializers import ProjectScoreCreateSerializer
from project_rates.criteria_policy import CriteriaConflict, mark_locked, revision
from users.models import Expert
from vacancy.mapping import ProjectRatedParams, MessageTypeEnum
from vacancy.tasks import send_email


class MaxProjectRatesReached(Exception):
    def __init__(self, max_project_rates: int):
        self.max_project_rates = max_project_rates
        super().__init__("max project rates reached for this program")


def get_rate_program(program_id: int) -> PartnerProgram:
    return PartnerProgram.objects.get(pk=program_id)


def extract_project_rate_filters(method: str, data) -> dict:
    """
    Accept filters from JSON body to mirror /partner_programs/<id>/projects/filter/:
    {"filters": {"case": ["Кейс 1"]}}
    """
    if method != "POST":
        return {}

    body_filters = data.get("filters") if isinstance(data, dict) else {}
    return body_filters if isinstance(body_filters, dict) else {}


def get_projects_for_rate_queryset(
    *,
    program: PartnerProgram,
    user,
    field_filters: dict,
) -> QuerySet[Project]:
    filters_serializer = ProgramProjectFilterRequestSerializer(
        data={"filters": field_filters}
    )
    filters_serializer.is_valid(raise_exception=True)
    validated_filters = filters_serializer.validated_data.get("filters", {})

    try:
        program_projects_qs = filter_program_projects_by_field_name(
            program, validated_filters
        )
    except ValueError as e:
        raise ValidationError({"filters": str(e)})

    project_ids = program_projects_qs.values_list("project_id", flat=True)

    scores_prefetch = Prefetch(
        "scores",
        queryset=ProjectScore.objects.filter(
            criteria__partner_program=program
        ).select_related("user"),
        to_attr="_program_scores",
    )

    projects_qs = Project.objects.filter(draft=False, id__in=project_ids)
    if program.is_distributed_evaluation or getattr(program, "assigned_only", False):
        projects_qs = projects_qs.filter(
            expert_assignments__partner_program=program,
            expert_assignments__expert__user=user,
        )

    return (
        projects_qs.annotate(
            rated_count=Count(
                "scores__user",
                filter=Q(scores__criteria__partner_program=program),
                distinct=True,
            )
        )
        .prefetch_related(scores_prefetch)
        .distinct()
    )


@transaction.atomic
def submit_project_scores(*, user, project_id: int, data) -> None:
    expected_revision = None
    if isinstance(data, dict):
        expected_revision = data.get("expected_revision")
        data = data.get("scores")
    if (
        not isinstance(data, list)
        or not data
        or any(not isinstance(row, dict) for row in data)
    ):
        raise ValidationError("Передайте непустой список оценок.")
    # Determine scope before locking; re-read all definitions and validate under the
    # same program lock used by organizer saves. Never validate against a stale scale.
    ids = [row.get("criterion_id") for row in data]
    if any(not isinstance(pk, int) or isinstance(pk, bool) for pk in ids) or len(
        set(ids)
    ) != len(ids):
        raise ValidationError("Некорректные ID критериев.")
    programs = set(
        Criteria.objects.filter(pk__in=ids).values_list("partner_program_id", flat=True)
    )
    if len(programs) != 1:
        if expected_revision:
            raise CriteriaConflict(
                "criteria_changed", "Критерии изменились. Обновите форму оценки."
            )
        raise ValueError("All criteria must belong to the same program")
    program = PartnerProgram.objects.select_for_update().get(pk=programs.pop())
    Expert.objects.get(user__id=user.id, programs=program)
    if (
        expected_revision is not None or program.evaluation_criteria_version
    ) and expected_revision != revision(program):
        raise CriteriaConflict(
            "criteria_changed",
            "Критерии изменились. Обновите форму оценки; введенные ответы сохранены в форме.",
        )
    rating_data, criteria_ids, program = _prepare_project_score_data(
        user=user,
        project_id=project_id,
        data=data,
    )

    serializer = ProjectScoreCreateSerializer(
        data=rating_data,
        criteria_to_get=criteria_ids,
        many=True,
    )
    serializer.is_valid(raise_exception=True)

    scores_qs = ProjectScore.objects.filter(
        project_id=project_id,
        criteria__partner_program=program,
    )
    user_has_scores = scores_qs.filter(user_id=user.id).exists()

    if program.max_project_rates and program.required_evaluators is None:
        distinct_raters = scores_qs.values("user_id").distinct().count()
        if not user_has_scores and distinct_raters >= program.max_project_rates:
            raise MaxProjectRatesReached(program.max_project_rates)

    with transaction.atomic():
        ProjectScore.objects.bulk_create(
            [ProjectScore(**item) for item in serializer.validated_data],
            update_conflicts=True,
            update_fields=["value"],
            unique_fields=["criteria", "user", "project"],
        )

    mark_locked(program)

    project = Project.objects.select_related("leader").get(id=project_id)
    _send_project_rated_email(project=project, program=program)


def _prepare_project_score_data(
    *, user, project_id: int, data
) -> tuple[list, list, PartnerProgram]:
    rating_data = [dict(criterion) for criterion in data]
    criteria_ids = [criterion["criterion_id"] for criterion in rating_data]

    criteria_qs = Criteria.objects.filter(id__in=criteria_ids).select_related(
        "partner_program"
    )
    partner_program_ids = criteria_qs.values_list(
        "partner_program_id", flat=True
    ).distinct()
    if not criteria_qs.exists():
        raise ValueError("Criteria not found")
    if partner_program_ids.count() != 1:
        raise ValueError("All criteria must belong to the same program")

    program = criteria_qs.first().partner_program
    Expert.objects.get(user__id=user.id, programs=program)

    if program.required_evaluators is not None:
        from projects.models import Collaborator

        if (
            program.datetime_evaluation_ends
            and timezone.now() > program.datetime_evaluation_ends
        ):
            raise ValidationError("Срок оценивания завершен.")

        required = set(program.criterias.exclude(type="str").values_list("pk", flat=True))
        if not required.issubset(criteria_ids):
            raise ValidationError(
                "Заполните все обязательные критерии и сохраните оценку целиком."
            )
        if not PartnerProgramProject.objects.filter(
            partner_program=program, project_id=project_id, submitted=True
        ).exists():
            raise ValidationError("Сначала нужно сдать решение.")
        if (
            Project.objects.filter(pk=project_id, leader=user).exists()
            or Collaborator.objects.filter(project_id=project_id, user=user).exists()
        ):
            raise ValidationError("Нельзя оценивать проект своей команды.")
        # Optional comments are stored too, keeping completion and legacy analytics consistent.
        present = set(criteria_ids)
        for criterion in program.criterias.filter(type="str").exclude(pk__in=present):
            rating_data.append({"criterion_id": criterion.pk, "value": ""})
            criteria_ids.append(criterion.pk)

    for criterion in rating_data:
        criterion["user"] = user.id
        criterion["project"] = project_id
        criterion["criteria"] = criterion.pop("criterion_id")

    if not PartnerProgramProject.objects.filter(
        partner_program=program,
        project_id=project_id,
    ).exists():
        raise ValueError("Project is not linked to the program")

    if (
        program.is_distributed_evaluation
        and not ProjectExpertAssignment.objects.filter(
            partner_program=program,
            project_id=project_id,
            expert__user_id=user.id,
        ).exists()
    ):
        raise ValueError("you are not assigned to rate this project")

    return rating_data, criteria_ids, program


def _send_project_rated_email(*, project: Project, program: PartnerProgram) -> None:
    send_email.delay(
        ProjectRatedParams(
            message_type=MessageTypeEnum.PROJECT_RATED.value,
            user_id=project.leader.id,
            project_name=project.name,
            project_id=project.id,
            schema_id=2,
            program_name=program.name,
        )
    )
