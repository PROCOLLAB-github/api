"""Program-scoped expert workspace. All organizer writes share the scoring lock."""

import hashlib
import json
import secrets
from collections import Counter, defaultdict
from datetime import timedelta

from django.core import signing
from django.db import transaction
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from partner_programs.models import PartnerProgram, PartnerProgramProject
from partner_programs.services.assignment_analytics import annotated_assignment_queryset
from partner_programs.services.case_analytics import project_case_links
from partner_programs.services.case_fields import get_program_case_field
from partner_programs.services.management import managed_program, person_name
from project_rates.models import ExpertInvitation, ProjectExpertAssignment, ProjectScore
from projects.models import Collaborator
from users.models import CustomUser, Expert


class WorkspaceConflict(APIException):
    status_code = 409

    def __init__(self, code, detail):
        super().__init__({"code": code, "detail": detail})


class InvitationGone(APIException):
    status_code = 410
    default_detail = (
        "Приглашение истекло или отозвано. Попросите организатора отправить новое."
    )


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def target(program):
    return program.required_evaluators or program.max_project_rates or 1


def expert_rows(program):
    return list(
        program.experts.filter(user__is_active=True).select_related("user").order_by("pk")
    )


def assignment_snapshot(program):
    return list(
        annotated_assignment_queryset(program.pk).select_related(
            "expert__user", "project"
        )
    )


def revision(program):
    """Includes team, membership, submission and score changes invalidating a plan."""
    data = [
        program.pk,
        program.required_evaluators,
        program.max_project_rates,
        program.is_distributed_evaluation,
        list(program.experts.order_by("pk").values_list("pk", "user__is_active")),
        list(
            program.project_expert_assignments.order_by("pk").values_list(
                "pk", "project_id", "expert_id"
            )
        ),
        list(
            PartnerProgramProject.objects.filter(partner_program=program)
            .order_by("pk")
            .values_list(
                "project_id", "submitted", "project__leader_id", "project__draft"
            )
        ),
        list(
            Collaborator.objects.filter(
                project_id__in=PartnerProgramProject.objects.filter(
                    partner_program=program
                ).values("project_id")
            )
            .order_by("pk")
            .values_list("project_id", "user_id")
        ),
        list(
            ProjectScore.objects.filter(criteria__partner_program=program)
            .order_by("pk")
            .values_list("pk", "project_id", "user_id", "criteria_id", "value")
        ),
        list(program.criterias.order_by("pk").values_list("pk", "type")),
    ]
    return digest(json.dumps(data, ensure_ascii=False, default=str))


def check_revision(program, expected):
    if expected != revision(program):
        raise WorkspaceConflict(
            "stale_assignments",
            "Данные изменились. Обновите список и проверьте изменения.",
        )


def enable_workspace(program):
    """Explicit organizer action opts in; preserve assignments behind historical scores."""
    if program.required_evaluators is not None:
        return
    program.required_evaluators = target(program)
    program.is_distributed_evaluation = True
    program.save(
        update_fields=[
            "required_evaluators",
            "is_distributed_evaluation",
            "datetime_updated",
        ]
    )
    historical = (
        ProjectScore.objects.filter(criteria__partner_program=program)
        .values_list("project_id", "user_id")
        .distinct()
    )
    members = dict(program.experts.values_list("user_id", "pk"))
    linked = set(
        PartnerProgramProject.objects.filter(partner_program=program).values_list(
            "project_id", flat=True
        )
    )
    ProjectExpertAssignment.objects.bulk_create(
        [
            ProjectExpertAssignment(
                partner_program=program, project_id=p, expert_id=members[u]
            )
            for p, u in historical
            if u in members and p in linked
        ],
        ignore_conflicts=True,
    )


def invitation_data(invitation):
    expired = invitation.status == "pending" and invitation.expires_at <= timezone.now()
    return {
        "id": invitation.pk,
        "email": invitation.email,
        "status": "expired" if expired else invitation.status,
        "delivery_status": invitation.delivery_status,
        "expires_at": invitation.expires_at,
        "created_at": invitation.created_at,
    }


def program_card(program):
    return {
        "id": program.pk,
        "name": program.name,
        "image_address": program.image_address,
        "image_framing": program.image_framing,
        "datetime_evaluation_ends": program.datetime_evaluation_ends,
    }


def workspace_data(program):
    assignments = assignment_snapshot(program)
    counts = Counter(a.expert_id for a in assignments)
    completed = Counter(a.expert_id for a in assignments if a.is_completed)
    invitations = list(
        program.expert_invitations.exclude(status="accepted").order_by("pk")
    )
    users = defaultdict(list)
    for account in CustomUser.objects.annotate(invitation_email=Lower("email")).filter(
        invitation_email__in=[i.email.lower() for i in invitations]
    ):
        users[account.invitation_email].append(account)
    members = expert_rows(program)
    rows = [
        {
            "id": e.pk,
            "user_id": e.user_id,
            "name": person_name(e.user),
            "email": e.user.email,
            "avatar": e.user.avatar,
            "status": "joined",
            "assigned": counts[e.pk],
            "completed": completed[e.pk],
            "remaining": counts[e.pk] - completed[e.pk],
        }
        for e in members
    ]
    joined_emails = {e.user.email.lower() for e in members}
    for invitation in invitations:
        if invitation.email in joined_emails:
            continue
        matches = users.get(invitation.email.lower(), [])
        # Старые аккаунты могут отличаться только регистром email: не выбираем чужое имя.
        user = matches[0] if len(matches) == 1 else None
        rows.append(
            {
                **invitation_data(invitation),
                "id": f"invite-{invitation.pk}",
                "invitation_id": invitation.pk,
                "name": person_name(user) if user else None,
                "avatar": user.avatar if user else None,
                "assigned": None,
                "completed": None,
                "remaining": None,
            }
        )
    submitted = list(
        PartnerProgramProject.objects.filter(partner_program=program, submitted=True)
        .values_list("project_id", flat=True)
        .distinct()
    )
    per_project = Counter(a.project_id for a in assignments)
    complete_project = Counter(a.project_id for a in assignments if a.is_completed)
    return {
        "revision": revision(program),
        "required_evaluators": target(program),
        "managed_evaluation": program.required_evaluators is not None,
        "submitted_projects": len(submitted),
        "projects_missing_experts": sum(
            per_project[p] < target(program) for p in submitted
        ),
        "missing_assignments": sum(
            max(0, target(program) - per_project[p]) for p in submitted
        ),
        "ready_projects": sum(complete_project[p] >= target(program) for p in submitted),
        "experts": rows,
    }


def token_invitation(token, *, lock=False, allow_accepted=False):
    if not isinstance(token, str) or not 20 <= len(token) <= 100:
        from django.http import Http404

        raise Http404
    qs = (
        ExpertInvitation.objects.select_for_update() if lock else ExpertInvitation.objects
    )
    invitation = get_object_or_404(
        qs.select_related("partner_program"), token_digest=digest(token)
    )
    if invitation.status == "accepted" and allow_accepted:
        return invitation
    if invitation.status != "pending" or invitation.expires_at <= timezone.now():
        raise InvitationGone()
    return invitation


@transaction.atomic
def invite(program_id, user, email, *, invitation_id=None):
    program = managed_program(program_id, user, lock=True)
    email = email.strip().lower()
    if program.experts.filter(user__email__iexact=email).exists():
        raise WorkspaceConflict("already_expert", "Этот эксперт уже в программе.")
    if invitation_id is None:
        previous = program.expert_invitations.filter(
            email=email, status="pending"
        ).first()
        if previous and previous.expires_at > timezone.now():
            raise WorkspaceConflict(
                "already_invited", "Приглашение уже отправлено. Можно отправить повторно."
            )
        if previous:
            previous.status = "revoked"
            previous.save(update_fields=["status", "updated_at"])
        invitation = ExpertInvitation(
            partner_program=program, email=email, invited_by=user
        )
    else:
        invitation = get_object_or_404(program.expert_invitations, pk=invitation_id)
        if invitation.status == "accepted":
            raise WorkspaceConflict("already_accepted", "Приглашение уже принято.")
        if (
            program.expert_invitations.filter(email=email, status="pending")
            .exclude(pk=invitation.pk)
            .exists()
        ):
            raise WorkspaceConflict(
                "already_invited", "Другое приглашение уже отправлено. Обновите список."
            )
    token = secrets.token_urlsafe(32)
    invitation.token_digest = digest(token)
    invitation.status = "pending"
    invitation.delivery_status = "queued"
    invitation.expires_at = timezone.now() + timedelta(days=7)
    invitation.save()
    enable_workspace(program)
    from project_rates.tasks import send_expert_invitation

    def enqueue():
        try:
            send_expert_invitation.delay(invitation.pk, token)
        except Exception:
            ExpertInvitation.objects.filter(
                pk=invitation.pk, token_digest=digest(token)
            ).update(delivery_status="failed")

    transaction.on_commit(enqueue)
    return invitation_data(invitation)


@transaction.atomic
def revoke(program_id, user, invitation_id):
    program = managed_program(program_id, user, lock=True)
    invitation = get_object_or_404(
        program.expert_invitations.select_for_update(), pk=invitation_id
    )
    if invitation.status == "accepted":
        raise WorkspaceConflict(
            "already_accepted", "Принятое приглашение нельзя отозвать."
        )
    invitation.status = "revoked"
    invitation.save(update_fields=["status", "updated_at"])


def accept_invitation(invitation, user):
    if (
        not user.is_authenticated
        or not user.is_active
        or user.email.lower() != invitation.email
    ):
        raise PermissionDenied("Войдите в аккаунт с почтой из приглашения.")
    if invitation.status == "accepted":
        if invitation.accepted_by_id != user.pk:
            raise PermissionDenied()
        return
    if invitation.status != "pending" or invitation.expires_at <= timezone.now():
        raise InvitationGone()
    expert, _ = Expert.objects.get_or_create(user=user)
    expert.programs.add(invitation.partner_program)
    invitation.status = "accepted"
    invitation.accepted_by = user
    invitation.save(update_fields=["status", "accepted_by", "updated_at"])


def my_programs(user):
    programs = list(
        PartnerProgram.objects.filter(experts__user=user)
        .distinct()
        .order_by("name", "pk")
    )
    rows = []
    for program in programs:
        assignments = list(
            annotated_assignment_queryset(program.pk).filter(expert__user=user)
        )
        done = sum(a.is_completed for a in assignments)
        rows.append(
            {
                **program_card(program),
                "status": "joined",
                "assigned": len(assignments),
                "completed": done,
                "remaining": len(assignments) - done,
            }
        )
    joined = {p.pk for p in programs}
    if user.is_active:
        pending = (
            ExpertInvitation.objects.filter(
                email__iexact=user.email, status="pending", expires_at__gt=timezone.now()
            )
            .select_related("partner_program")
            .order_by("pk")
        )
        rows.extend(
            {
                **program_card(i.partner_program),
                "status": "pending",
                "email": i.email,
                "invitation_id": i.pk,
            }
            for i in pending
            if i.partner_program_id not in joined
        )
    return {"results": rows, "has_access": bool(rows)}


def own_projects(user_id, project_ids):
    leaders = PartnerProgramProject.objects.filter(
        project_id__in=project_ids, project__leader_id=user_id
    ).values_list("project_id", flat=True)
    collaborators = Collaborator.objects.filter(
        project_id__in=project_ids, user_id=user_id
    ).values_list("project_id", flat=True)
    return set(leaders) | set(collaborators)


def assignment_options(program, expert_id):
    expert = get_object_or_404(program.experts.filter(user__is_active=True), pk=expert_id)
    links = list(
        project_case_links(program, field=get_program_case_field(program))
        .select_related("project")
        .order_by("project_id")
    )
    assignments = {
        a.project_id: a for a in assignment_snapshot(program) if a.expert_id == expert.pk
    }
    protected = set(
        ProjectScore.objects.filter(
            criteria__partner_program=program, user=expert.user
        ).values_list("project_id", flat=True)
    )
    own = own_projects(expert.user_id, [p.project_id for p in links])
    return {
        "revision": revision(program),
        "projects": [
            {
                "id": p.project_id,
                "name": p.project.name,
                "case_name": p.case_name,
                "submitted": p.submitted and not p.project.draft,
                "assigned": p.project_id in assignments or p.project_id in protected,
                "protected": p.project_id in protected,
                "completed": bool(
                    assignments.get(p.project_id)
                    and assignments[p.project_id].is_completed
                ),
                "own_team": p.project_id in own,
            }
            for p in links
        ],
    }


@transaction.atomic
def save_assignments(program_id, user, expert_id, data):
    program = managed_program(program_id, user, lock=True)
    check_revision(program, data["revision"])
    expert = get_object_or_404(program.experts.filter(user__is_active=True), pk=expert_id)
    wanted = set(data["project_ids"])
    options = {p["id"]: p for p in assignment_options(program, expert.pk)["projects"]}
    existing = set(
        program.project_expert_assignments.filter(expert=expert).values_list(
            "project_id", flat=True
        )
    )
    for project_id in wanted - existing:
        option = options.get(project_id)
        if not option or not option["submitted"] or option["own_team"]:
            raise ValidationError(
                "Можно назначить только сданный проект этой программы, кроме своей команды."
            )
    protected = set(
        ProjectScore.objects.filter(
            criteria__partner_program=program, user=expert.user
        ).values_list("project_id", flat=True)
    )
    if protected - wanted:
        raise WorkspaceConflict(
            "scores_protected", "Нельзя снять назначение с сохранёнными оценками."
        )
    enable_workspace(program)
    program.project_expert_assignments.filter(
        expert=expert, project_id__in=existing - wanted
    ).delete()
    ProjectExpertAssignment.objects.bulk_create(
        [
            ProjectExpertAssignment(partner_program=program, expert=expert, project_id=p)
            for p in sorted(wanted - existing)
        ],
        ignore_conflicts=True,
    )
    return assignment_options(program, expert.pk)


def allocation(program, data):
    experts = expert_rows(program)
    selected = set(data["expert_ids"])
    if not selected or selected - {e.pk for e in experts}:
        raise ValidationError("Выберите принявших приглашение экспертов этой программы.")
    experts = [e for e in experts if e.pk in selected]
    links = list(
        PartnerProgramProject.objects.filter(
            partner_program=program, submitted=True, project__draft=False
        )
        .select_related("project")
        .order_by("project_id")
    )
    if "project_ids" in data:
        ids = set(data["project_ids"])
        if ids - {p.project_id for p in links}:
            raise ValidationError("Выберите сданные проекты этой программы.")
        links = [p for p in links if p.project_id in ids]
    assignments = assignment_snapshot(program)
    present = {(a.project_id, a.expert_id) for a in assignments}
    counts = Counter(a.project_id for a in assignments)
    remaining = Counter(a.expert_id for a in assignments if not a.is_completed)
    before = remaining.copy()
    teams = defaultdict(set)
    for link in links:
        teams[link.project.leader_id].add(link.project_id)
    for project_id, user_id in Collaborator.objects.filter(
        project_id__in=[p.project_id for p in links],
        user_id__in=[e.user_id for e in experts],
    ).values_list("project_id", "user_id"):
        teams[user_id].add(project_id)
    own = {e.pk: teams[e.user_id] for e in experts}
    additions, shortages = [], []
    for link in links:
        needed = max(0, target(program) - counts[link.project_id])
        candidates = [
            e
            for e in experts
            if (link.project_id, e.pk) not in present and link.project_id not in own[e.pk]
        ]
        candidates.sort(key=lambda e: (remaining[e.pk], e.pk))
        for expert in candidates[:needed]:
            additions.append(
                {
                    "project_id": link.project_id,
                    "project_name": link.project.name,
                    "expert_id": expert.pk,
                    "expert_name": person_name(expert.user),
                }
            )
            remaining[expert.pk] += 1
        if len(candidates) < needed:
            shortages.append(
                {
                    "project_id": link.project_id,
                    "project_name": link.project.name,
                    "missing": needed - len(candidates),
                }
            )
    rev = revision(program)
    token = signing.dumps(
        {
            "program_id": program.pk,
            "revision": rev,
            "has_shortages": bool(shortages),
            "additions": [
                {"project_id": a["project_id"], "expert_id": a["expert_id"]}
                for a in additions
            ],
        },
        salt="expert-allocation",
        compress=True,
    )
    return {
        "revision": rev,
        "plan_token": token,
        "assignments": additions,
        "shortages": shortages,
        "load": [
            {
                "expert_id": e.pk,
                "name": person_name(e.user),
                "before": before[e.pk],
                "after": remaining[e.pk],
            }
            for e in experts
        ],
    }


@transaction.atomic
def apply_allocation(program_id, user, token):
    program = managed_program(program_id, user, lock=True)
    try:
        plan = signing.loads(token, salt="expert-allocation", max_age=900)
    except signing.BadSignature:
        raise WorkspaceConflict(
            "stale_plan", "Предпросмотр устарел. Рассчитайте распределение заново."
        )
    if plan.get("program_id") != program.pk:
        raise ValidationError("План принадлежит другой программе.")
    check_revision(program, plan["revision"])
    if plan.get("has_shortages"):
        raise WorkspaceConflict(
            "expert_shortage", "Не хватает экспертов. Измените параметры распределения."
        )
    enable_workspace(program)
    ProjectExpertAssignment.objects.bulk_create(
        [
            ProjectExpertAssignment(partner_program=program, **row)
            for row in plan["additions"]
        ],
        ignore_conflicts=True,
    )
    return workspace_data(program)


def quota_preview(program, number):
    assignments = assignment_snapshot(program)
    completed = Counter(a.project_id for a in assignments if a.is_completed)
    counts = Counter(a.project_id for a in assignments)
    ids = set(
        PartnerProgramProject.objects.filter(
            partner_program=program, submitted=True
        ).values_list("project_id", flat=True)
    )
    return {
        "revision": revision(program),
        "required_evaluators": number,
        "submitted_projects": len(ids),
        "projects_missing_experts": sum(counts[p] < number for p in ids),
        "ready_before": sum(completed[p] >= target(program) for p in ids),
        "ready_after": sum(completed[p] >= number for p in ids),
        "missing_assignments": sum(max(0, number - counts[p]) for p in ids),
        "surplus_assignments": sum(max(0, counts[p] - number) for p in ids),
    }


@transaction.atomic
def save_quota(program_id, user, data):
    program = managed_program(program_id, user, lock=True)
    check_revision(program, data["revision"])
    enable_workspace(program)
    program.required_evaluators = data["required_evaluators"]
    program.save(update_fields=["required_evaluators", "datetime_updated"])
    return workspace_data(program)
