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
from project_rates.models import (
    ExpertCaseScope,
    ExpertInvitation,
    ProjectExpertAssignment,
    ProjectScore,
)
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
        list(
            program.expert_case_scopes.order_by("expert_id").values_list(
                "expert_id", "all_cases", "case_names"
            )
        ),
        list(program.fields.filter(name="case").values_list("pk", "options")),
        list(
            program.expert_invitations.order_by("pk").values_list(
                "pk", "status", "all_cases", "case_names"
            )
        ),
        list(
            project_case_links(program, field=get_program_case_field(program))
            .order_by("project_id")
            .values_list("project_id", "case_name")
        ),
    ]
    return digest(json.dumps(data, ensure_ascii=False, default=str))


def check_revision(program, expected):
    if expected != revision(program):
        raise WorkspaceConflict(
            "stale_assignments",
            "Данные изменились. Обновите список и проверьте изменения.",
        )


def check_assignment_limit(program, additions, removals=()):
    """Preserve historical surplus, but never create a new over-quota assignment."""
    present = set(
        program.project_expert_assignments.values_list("project_id", "expert_id")
    ) - set(removals)
    new = set(additions) - present
    counts = Counter(project_id for project_id, _ in present | new)
    if any(counts[project_id] > target(program) for project_id, _ in new):
        raise WorkspaceConflict(
            "expert_limit_reached",
            "Нельзя назначить больше экспертов, чем требуется оценок на проект. "
            "Для замены снимите назначение эксперта без оценки.",
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


def expert_invitation_data(invitation):
    return {
        **invitation_data(invitation),
        "all_cases": invitation.all_cases,
        "case_names": invitation.case_names,
    }


def program_card(program):
    return {
        "id": program.pk,
        "name": program.name,
        "image_address": program.image_address,
        "image_framing": program.image_framing,
        "datetime_evaluation_ends": program.datetime_evaluation_ends,
    }


def invited_account(accounts):
    # В legacy-базе регистр email мог породить неподтверждённый дубль аккаунта.
    # Принять приглашение может только активный пользователь; выбираем его,
    # если он единственный. Неоднозначные активные аккаунты не угадываем.
    active = [account for account in accounts if account.is_active]
    candidates = active or accounts
    return candidates[0] if len(candidates) == 1 else None


def submitted_links(program):
    return list(
        PartnerProgramProject.objects.filter(partner_program=program, submitted=True)
        .select_related("project")
        .order_by("project_id")
    )


def unavailable_projects(links):
    return [
        {
            "project_id": link.project_id,
            "project_name": link.project.name,
            "reason": "draft",
        }
        for link in links
        if link.project.draft
    ]


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
    scopes = {s.expert_id: s for s in program.expert_case_scopes.all()}
    valid_cases = {None, *program_cases(program)}
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
            "all_cases": e.pk not in scopes or scopes[e.pk].all_cases,
            "case_names": [
                name for name in scopes[e.pk].case_names if name in valid_cases
            ]
            if e.pk in scopes
            else [],
        }
        for e in members
    ]
    joined_emails = {e.user.email.lower() for e in members}
    for invitation in invitations:
        if invitation.email in joined_emails:
            continue
        matches = users.get(invitation.email.lower(), [])
        user = invited_account(matches)
        rows.append(
            {
                **expert_invitation_data(invitation),
                "id": f"invite-{invitation.pk}",
                "invitation_id": invitation.pk,
                "name": person_name(user) if user else None,
                "avatar": user.avatar if user else None,
                "assigned": None,
                "completed": None,
                "remaining": None,
            }
        )
    links = submitted_links(program)
    submitted = {link.project_id for link in links}
    per_project = Counter(a.project_id for a in assignments)
    complete_project = Counter(a.project_id for a in assignments if a.is_completed)
    return {
        "revision": revision(program),
        "required_evaluators": target(program),
        "managed_evaluation": program.required_evaluators is not None,
        "submitted_projects": len(submitted),
        "unavailable_projects": unavailable_projects(links),
        "projects_missing_experts": sum(
            per_project[p] < target(program) for p in submitted
        ),
        "missing_assignments": sum(
            max(0, target(program) - per_project[p]) for p in submitted
        ),
        "ready_projects": sum(complete_project[p] >= target(program) for p in submitted),
        "experts": rows,
        "cases": program_cases(program),
        "projects": distribution_projects(program, assignments),
    }


def program_cases(program):
    field = get_program_case_field(program)
    return field.get_options_list() if field else []


def eligible(scope, case_name):
    return scope is None or scope.all_cases or case_name in scope.case_names


def distribution_projects(program, assignments=None):
    assignments = assignment_snapshot(program) if assignments is None else assignments
    protected = set(
        ProjectScore.objects.filter(criteria__partner_program=program).values_list(
            "project_id", "user_id"
        )
    )
    teams = defaultdict(list)
    for pid, uid in Collaborator.objects.filter(
        project_id__in=PartnerProgramProject.objects.filter(
            partner_program=program
        ).values("project_id")
    ).values_list("project_id", "user_id"):
        teams[pid].append(uid)
    by_project = defaultdict(list)
    for assignment in assignments:
        by_project[assignment.project_id].append(
            {
                "expert_id": assignment.expert_id,
                "name": person_name(assignment.expert.user),
                "email": assignment.expert.user.email,
                "completed": bool(assignment.is_completed),
                "protected": (assignment.project_id, assignment.expert.user_id)
                in protected,
            }
        )
    links = project_case_links(program, field=get_program_case_field(program))
    return [
        {
            "id": link.project_id,
            "name": link.project.name,
            "case_name": link.case_name,
            "leader_id": link.project.leader_id,
            "team_user_ids": teams[link.project_id],
            "experts": by_project[link.project_id],
        }
        for link in links.filter(submitted=True, project__draft=False)
        .select_related("project")
        .order_by("project_id")
    ]


@transaction.atomic
def save_case_scope(program_id, user, expert_id, data):
    program = managed_program(program_id, user, lock=True)
    check_revision(program, data["revision"])
    expert = get_object_or_404(program.experts.filter(user__is_active=True), pk=expert_id)
    scope = validated_case_scope(program, data)
    ExpertCaseScope.objects.update_or_create(
        partner_program=program, expert=expert, defaults=scope
    )
    return workspace_data(program)


@transaction.atomic
def bulk_experts(program_id, user, data):
    program = managed_program(program_id, user, lock=True)
    check_revision(program, data["revision"])
    expert_ids, invitation_ids = set(data["expert_ids"]), set(data["invitation_ids"])
    experts = list(
        program.experts.filter(pk__in=expert_ids, user__is_active=True).order_by("pk")
    )
    invitations = list(
        program.expert_invitations.select_for_update()
        .filter(pk__in=invitation_ids)
        .order_by("pk")
    )
    if len(experts) != len(expert_ids) or len(invitations) != len(invitation_ids):
        raise ValidationError(
            "Выбор содержит экспертов другой программы или удаленные записи."
        )
    if any(i.status == "accepted" for i in invitations):
        raise WorkspaceConflict(
            "already_accepted", "Одно из приглашений уже принято. Обновите список."
        )
    action = data["action"]
    if action == "cases":
        scope = validated_case_scope(program, data, require_selection=True)
        for expert in experts:
            ExpertCaseScope.objects.update_or_create(
                partner_program=program, expert=expert, defaults=scope
            )
        for invitation in invitations:
            invitation.all_cases, invitation.case_names = (
                scope["all_cases"],
                scope["case_names"],
            )
            invitation.save(update_fields=["all_cases", "case_names", "updated_at"])
    elif expert_ids:
        raise ValidationError("Выберите только приглашения.")
    elif action == "revoke":
        for invitation in invitations:
            revoke(program_id, user, invitation.pk)
    else:
        for invitation in invitations:
            invite(program_id, user, invitation.email, invitation_id=invitation.pk)
    return workspace_data(program)


def validated_case_scope(program, data, *, require_selection=False):
    names = data["case_names"]
    if any(name is not None and name not in program_cases(program) for name in names):
        raise ValidationError("Выберите кейсы этой программы.")
    if require_selection and not data["all_cases"] and not names:
        raise ValidationError("Выберите хотя бы один кейс или все кейсы.")
    return {
        "all_cases": data["all_cases"],
        "case_names": [] if data["all_cases"] else list(dict.fromkeys(names)),
    }


@transaction.atomic
def save_invitation_case_scope(program_id, user, invitation_id, data):
    program = managed_program(program_id, user, lock=True)
    check_revision(program, data["revision"])
    invitation = get_object_or_404(program.expert_invitations, pk=invitation_id)
    if invitation.status == "accepted":
        raise WorkspaceConflict(
            "already_accepted", "Приглашение уже принято. Обновите список экспертов."
        )
    scope = validated_case_scope(program, data, require_selection=True)
    invitation.all_cases, invitation.case_names = scope["all_cases"], scope["case_names"]
    invitation.save(update_fields=["all_cases", "case_names", "updated_at"])
    return workspace_data(program)


@transaction.atomic
def save_project_experts(program_id, user, data):
    program = managed_program(program_id, user, lock=True)
    check_revision(program, data["revision"])
    enable_workspace(program)
    ids, wanted = set(data["project_ids"]), set(data["expert_ids"])
    projects = {p["id"]: p for p in distribution_projects(program)}
    experts = {e.pk: e for e in expert_rows(program)}
    existing = {(a.project_id, a.expert_id): a for a in assignment_snapshot(program)}
    unavailable = wanted - experts.keys()
    keep_historical = all((pid, eid) in existing for pid in ids for eid in unavailable)
    if not ids or ids - projects.keys() or not keep_historical:
        raise ValidationError(
            "Выберите сданные проекты и активных экспертов этой программы."
        )
    if len(ids) > 1 and len({projects[p]["case_name"] for p in ids}) > 1:
        raise ValidationError("Для массового назначения выберите проекты одного кейса.")
    replace = data["mode"] == "replace"
    if replace and len(ids) != 1:
        raise ValidationError("Замена состава доступна только для одного проекта.")
    scopes = {s.expert_id: s for s in program.expert_case_scopes.all()}
    additions, removals = [], []
    for project_id in ids:
        project = projects[project_id]
        for expert_id in wanted:
            if (project_id, expert_id) in existing:
                continue
            expert = experts[expert_id]
            if not eligible(scopes.get(expert_id), project["case_name"]):
                raise ValidationError("Эксперт не выбран для кейса этого проекта.")
            if expert.user_id in {project["leader_id"], *project["team_user_ids"]}:
                raise ValidationError("Эксперт не может оценивать проект своей команды.")
            additions.append(
                ProjectExpertAssignment(
                    partner_program=program, project_id=project_id, expert_id=expert_id
                )
            )
        if replace:
            for (pid, eid), assignment in existing.items():
                if pid == project_id and eid not in wanted:
                    if assignment.has_scores():
                        raise WorkspaceConflict(
                            "scores_protected",
                            "Нельзя снять эксперта с сохраненной оценкой.",
                        )
                    removals.append(assignment.pk)
    check_assignment_limit(
        program,
        [(a.project_id, a.expert_id) for a in additions],
        [(pid, eid) for (pid, eid), a in existing.items() if a.pk in removals],
    )
    program.project_expert_assignments.filter(pk__in=removals).delete()
    ProjectExpertAssignment.objects.bulk_create(additions, ignore_conflicts=True)
    return workspace_data(program)


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
def invite(program_id, user, email, *, invitation_id=None, scope=None):
    program = managed_program(program_id, user, lock=True)
    email = email.strip().lower()
    if program.experts.filter(user__email__iexact=email).exists():
        raise WorkspaceConflict("already_expert", "Этот эксперт уже в программе.")
    if invitation_id is None:
        if scope is None:
            if program_cases(program):
                raise ValidationError("Выберите кейсы эксперта перед приглашением.")
            scope = {"all_cases": True, "case_names": []}
        scope = validated_case_scope(program, scope, require_selection=True)
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
            partner_program=program, email=email, invited_by=user, **scope
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
    return expert_invitation_data(invitation)


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
    ExpertCaseScope.objects.update_or_create(
        partner_program=invitation.partner_program,
        expert=expert,
        defaults={"all_cases": invitation.all_cases, "case_names": invitation.case_names},
    )
    invitation.status = "accepted"
    invitation.accepted_by = user
    invitation.save(update_fields=["status", "accepted_by", "updated_at"])
    from project_rates.notifications import notify_expert_joined

    notify_expert_joined(invitation, user)


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
    scope = program.expert_case_scopes.filter(expert=expert).first()
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
                "eligible": eligible(scope, p.case_name),
            }
            for p in links
        ],
    }


@transaction.atomic
def save_assignments(program_id, user, expert_id, data):
    program = managed_program(program_id, user, lock=True)
    check_revision(program, data["revision"])
    enable_workspace(program)
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
        if (
            not option
            or not option["submitted"]
            or option["own_team"]
            or not option["eligible"]
        ):
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
            "scores_protected", "Нельзя снять назначение с сохраненными оценками."
        )
    check_assignment_limit(program, [(pid, expert.pk) for pid in wanted - existing])
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
    if (not selected and "case_pools" not in data) or selected - {e.pk for e in experts}:
        raise ValidationError("Выберите принявших приглашение экспертов этой программы.")
    if "revision" in data:
        check_revision(program, data["revision"])
    scopes = {s.expert_id: s for s in program.expert_case_scopes.all()}
    pools = None
    if "case_pools" in data:
        pools = {}
        for pool in data["case_pools"]:
            name, members = pool["case_name"], set(pool["expert_ids"])
            if name in pools or (name is not None and name not in program_cases(program)):
                raise ValidationError("Проверьте список кейсов распределения.")
            if members - selected or any(
                not eligible(scopes.get(eid), name) for eid in members
            ):
                raise ValidationError("Выберите подходящих экспертов для каждого кейса.")
            pools[name] = members
    experts = [e for e in experts if e.pk in selected]
    submitted = list(
        project_case_links(program, field=get_program_case_field(program))
        .filter(submitted=True)
        .select_related("project")
        .order_by("project_id")
    )
    excluded = unavailable_projects(submitted) if "project_ids" not in data else []
    links = [link for link in submitted if not link.project.draft]
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
            if (link.project_id, e.pk) not in present
            and link.project_id not in own[e.pk]
            and eligible(scopes.get(e.pk), link.case_name)
            and (pools is None or e.pk in pools.get(link.case_name, set()))
        ]
        candidates.sort(key=lambda e: (remaining[e.pk], e.pk))
        for expert in candidates[:needed]:
            additions.append(
                {
                    "project_id": link.project_id,
                    "project_name": link.project.name,
                    "expert_id": expert.pk,
                    "expert_name": person_name(expert.user),
                    "case_name": link.case_name,
                }
            )
            remaining[expert.pk] += 1
        if len(candidates) < needed:
            shortages.append(
                {
                    "project_id": link.project_id,
                    "project_name": link.project.name,
                    "missing": needed - len(candidates),
                    "case_name": link.case_name,
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
        "unavailable_projects": excluded,
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
    check_assignment_limit(
        program, [(row["project_id"], row["expert_id"]) for row in plan["additions"]]
    )
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
