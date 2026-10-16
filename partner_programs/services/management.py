"""Program-scoped чтение для организатора без изменений участников и проектов."""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.permissions import can_manage_program
from partner_programs.serializers.management import BASIC_FIELDS, DATE_FIELDS
from partner_programs.services.analytics import _solution_rows
from partner_programs.services.case_analytics import project_case_links
from project_rates.models import Criteria, ProjectScore
from project_rates.services import get_projects_for_rate_queryset
from partner_programs.services.assignment_analytics import (
    assignment_rows,
    build_assignment,
)
from django.utils import timezone


def managed_program(pk, user, *, lock=False):
    rows = (
        PartnerProgram.objects.select_for_update()
        if lock
        else PartnerProgram.objects.all()
    )
    program = get_object_or_404(rows, pk=pk)
    if not can_manage_program(user, program):
        raise PermissionDenied("У вас нет доступа к управлению этой программой.")
    return program


def person_name(user):
    return (
        " ".join(filter(None, (user.first_name, user.last_name, user.patronymic))).strip()
        or "Без имени"
    )


def material_data(material):
    file = material.file
    return {
        "id": material.pk,
        "title": material.title,
        "url": material.url,
        "file": {
            "link": file.link,
            "name": file.name,
            "extension": file.extension,
            "size": file.size,
        }
        if file
        else None,
        "updated_at": material.datetime_updated,
    }


def management_data(program):
    return {
        "id": program.pk,
        **{name: getattr(program, name) for name in (*BASIC_FIELDS, *DATE_FIELDS)},
        "updated_at": program.datetime_updated,
        "is_competitive": program.is_competitive,
        "is_distributed_evaluation": program.is_distributed_evaluation,
        "materials": [
            material_data(m)
            for m in program.materials.select_related("file").order_by("pk")
        ],
    }


def participant_rows(program, search):
    rows = (
        PartnerProgramUserProfile.objects.filter(
            partner_program=program, user__isnull=False
        )
        .select_related("user")
        .order_by("datetime_created", "pk")
    )
    if search:
        # Каждый фрагмент может совпадать с любой частью ФИО или почты.
        for part in search.split():
            rows = rows.filter(
                Q(user__first_name__icontains=part)
                | Q(user__last_name__icontains=part)
                | Q(user__patronymic__icontains=part)
                | Q(user__email__icontains=part)
            )
    return rows


def participant_data(profile):
    return {
        "id": profile.pk,
        "user_id": profile.user_id,
        "name": person_name(profile.user),
        "email": profile.user.email,
        "city": profile.user.city,
        "registered_at": profile.datetime_created,
    }


def management_project_rows(program, query, field):
    rows = _solution_rows(
        program, rows=project_case_links(program, field=field)
    ).select_related("project", "project__leader")
    if query["search"]:
        rows = rows.filter(project__name__icontains=query["search"])
    if query["submission"] != "all":
        rows = rows.filter(submitted=query["submission"] == "submitted")
    if query["case_scope"] == "selected":
        rows = rows.filter(case_name=query["case_name"])
    elif query["case_scope"] == "without_case":
        rows = rows.filter(case_name__isnull=True)
    return rows.order_by("datetime_created", "pk")


def project_data(link, program):
    status = link.status if program.is_competitive else "not_applicable"
    return {
        "id": link.pk,
        "project_id": link.project_id,
        "name": link.project.name,
        "leader": {
            "id": link.project.leader_id,
            "name": person_name(link.project.leader),
        },
        "submitted": link.submitted,
        "evaluation_status": status,
        "assignments_total": link.assignments_total,
        "assignments_completed": link.assignments_completed,
        "case_name": link.case_name,
        "presentation_url": link.project.presentation_address,
    }


def managed_project(program, link_id):
    return get_object_or_404(
        PartnerProgramProject.objects.select_related("project", "project__leader"),
        pk=link_id,
        partner_program=program,
    )


def team_data(link):
    project = link.project
    people = [
        {
            "id": project.leader_id,
            "name": person_name(project.leader),
            "role": "Руководитель",
        }
    ]
    people.extend(
        {
            "id": member.user_id,
            "name": person_name(member.user),
            "role": member.role or "Участник команды",
        }
        for member in project.collaborator_set.select_related("user")
        .exclude(user_id=project.leader_id)
        .order_by("pk")
    )
    return {
        "project_id": project.pk,
        "program_link_id": link.pk,
        "name": project.name,
        "members": people,
    }


def evaluation_data(program, link, user):
    criteria = list(Criteria.objects.filter(partner_program=program).order_by("pk"))
    scores = list(
        ProjectScore.objects.filter(
            project_id=link.project_id, criteria__partner_program=program
        )
        .select_related("user")
        .order_by("user_id", "criteria_id")
    )
    assignments = (
        [
            build_assignment(row, now=timezone.now())
            for row in assignment_rows(program.pk).filter(project_id=link.project_id)
        ]
        if program.is_distributed_evaluation
        else []
    )
    experts = {
        a["expert"]["user_id"]: {
            "id": a["expert"]["user_id"],
            "name": a["expert"]["full_name"],
            "status": a["status"],
        }
        for a in assignments
    }
    for score in scores:
        experts.setdefault(
            score.user_id,
            {"id": score.user_id, "name": person_name(score.user), "status": "completed"},
        )
    values = {(s.user_id, s.criteria_id): s.value for s in scores}
    for expert in experts.values():
        expert["criteria"] = [
            {
                "id": c.pk,
                "name": c.name,
                "type": c.type,
                "value": values.get((expert["id"], c.pk)),
                "is_scored": (expert["id"], c.pk) in values,
            }
            for c in criteria
        ]
    eligible = (
        program.is_competitive
        and link.submitted
        and user.user_type == 3
        and program.experts.filter(user_id=user.pk).exists()
    )
    can_rate = bool(
        eligible
        and get_projects_for_rate_queryset(program=program, user=user, field_filters={})
        .filter(pk=link.project_id)
        .exists()
    )
    return {
        "project_id": link.project_id,
        "program_link_id": link.pk,
        "name": link.project.name,
        "submitted": link.submitted,
        "can_rate": can_rate,
        "experts": list(experts.values()),
    }
