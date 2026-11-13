"""Read projection of the current expert's actual assignments; no new scoring states."""

from django.db.models import Count, Exists, F, OuterRef, Q, Subquery
from django.utils import timezone

from partner_programs.models import PartnerProgram, PartnerProgramProject
from partner_programs.services.assignment_analytics import annotated_assignment_queryset
from partner_programs.services.case_analytics import project_case_links
from partner_programs.services.case_fields import get_program_case_field
from project_rates.models import ProjectScore
from project_rates.program_experts import evaluation_programs
from project_rates.project_scoring import project_scoring_blocker
from projects.models import Collaborator


def cabinet_projects(
    user,
    query,
    program_ids,
    *,
    paginate=True,
    as_applications=False,
    project_filters: Q | None = None,
):
    own = (
        annotated_assignment_queryset(expert_completion=True)
        .filter(
            expert__user=user,
            partner_program_id__in=program_ids,
        )
        .filter(
            partner_program_id__in=evaluation_programs(user).values("pk"),
        )
    )
    linked = PartnerProgramProject.objects.filter(
        partner_program_id=OuterRef("partner_program_id"),
        project_id=OuterRef("project_id"),
    )
    visible = own.filter(project__draft=False).filter(Exists(linked))
    pending = visible.filter(is_completed=False).count()
    completed = visible.filter(is_completed=True).count()
    unavailable = own.count() - pending - completed
    selected = visible.filter(is_completed=query["status"] == "completed")
    if query.get("program_id"):
        selected = selected.filter(partner_program_id=query["program_id"])
    if query.get("q"):
        selected = selected.filter(project__name__icontains=query["q"])
    if project_filters is not None:
        selected = selected.filter(project_filters)
    count = selected.count()
    scores = (
        ProjectScore.objects.filter(
            project_id=OuterRef("project_id"),
            criteria__partner_program_id=OuterRef("partner_program_id"),
        )
        .order_by()
        .values("project_id")
        .annotate(total=Count("user_id", distinct=True))
    )
    own_scores = ProjectScore.objects.filter(
        project_id=OuterRef("project_id"),
        criteria__partner_program_id=OuterRef("partner_program_id"),
        user_id=user.pk,
    )
    selected = selected.annotate(
        cabinet_program_link_id=Subquery(linked.values("pk")[:1]),
        cabinet_rated_count=Subquery(scores.values("total")[:1]),
        cabinet_has_scores=Exists(own_scores),
        cabinet_own_team=Exists(
            Collaborator.objects.filter(
                project_id=OuterRef("project_id"), user_id=user.pk
            )
        ),
        cabinet_organizer=Exists(
            PartnerProgram.managers.through.objects.filter(
                partnerprogram_id=OuterRef("partner_program_id"), customuser_id=user.pk
            )
        ),
    ).select_related("partner_program", "project")
    offset, limit = query["offset"], query["limit"]
    end = offset + limit
    selected = selected.order_by(
        F("partner_program__datetime_evaluation_ends").asc(nulls_last=True),
        "partner_program_id",
        "project__name",
        "pk",
    )
    assignments = list(selected[offset:end] if paginate else selected)
    programs = {a.partner_program_id: a.partner_program for a in assignments}
    cases = {}
    for program in programs.values():
        cases.update(
            {
                (program.pk, project_id): name
                for project_id, name in project_case_links(
                    program, field=get_program_case_field(program)
                )
                .filter(project_id__in=[a.project_id for a in assignments])
                .values_list("project_id", "case_name")
            }
        )
    now = timezone.now()
    rows = []
    for assignment in assignments:
        program, project = assignment.partner_program, assignment.project
        reason = project_scoring_blocker(
            program,
            now=now,
            has_criteria=assignment.criteria_total > 0,
            submitted=assignment.project_submitted,
            own_team=project.leader_id == user.pk or assignment.cabinet_own_team,
            is_organizer=assignment.cabinet_organizer,
            rated_count=assignment.cabinet_rated_count or 0,
            has_own_scores=assignment.cabinet_has_scores,
        )
        rows.append(
            {
                "assignment_id": assignment.pk,
                "project_id": project.pk,
                "program_id": program.pk,
                "name": project.name,
                "case_name": cases.get((program.pk, project.pk)),
                "is_completed": assignment.is_completed,
                "can_rate": reason is None,
                "blocked_reason": reason,
            }
        )
        if as_applications:
            from partner_programs.solution_api import iso

            row = rows[-1]
            rows[-1] = dict(
                application=dict(
                    kind="legacy_project",
                    program_id=program.pk,
                    project_id=project.pk,
                    program_link_id=assignment.cabinet_program_link_id,
                    name=project.name,
                ),
                assignment_id=assignment.pk,
                program=dict(id=program.pk, name=program.name),
                deadline=iso(program.datetime_evaluation_ends),
                case_name=row["case_name"],
                is_completed=row["is_completed"],
                can_rate=row["can_rate"],
                blocked_reason=row["blocked_reason"],
            )
    return {
        "count": count,
        "limit": limit,
        "offset": offset,
        "pending": pending,
        "completed": completed,
        "unavailable": unavailable,
        "results": rows,
    }
