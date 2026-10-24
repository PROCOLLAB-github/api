"""Основа контракта C00: контекст, создание и чтение. Команды BE02–BE06 закрыты."""

import hashlib
import json

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from rest_framework import serializers
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from partner_programs.permissions import can_manage_program
from partner_programs.services.role_analytics import participant_project_links
from partner_programs.solution_models import ProgramSolution, ProgramSolutionMember

MAX_ID = 2**53 - 1
VALIDATION_DEFAULTS = dict(
    min_length=None,
    max_length=None,
    minimum=None,
    maximum=None,
    allowed_extensions=[],
    max_file_size_bytes=None,
)


class SolutionError(APIException):
    def __init__(self, code, detail, status=409, *, errors=None, meta=None):
        self.status_code = status
        self.payload = dict(
            code=code, detail=detail, errors=errors or [], meta=meta or {}
        )
        super().__init__(detail=detail, code=code)


def issue(path, code, detail, field_id=None):
    return dict(path=path, code=code, detail=detail, field_id=field_id)


def iso(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def user_data(user):
    return dict(
        id=user.pk,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar or None,
    )


def program_for(pk, *, lock=False):
    if not 0 < pk <= MAX_ID:
        raise Http404
    query = PartnerProgram.objects.select_for_update() if lock else PartnerProgram.objects
    try:
        return query.get(pk=pk)
    except PartnerProgram.DoesNotExist:
        raise Http404


def current_application(program, user):
    solutions = list(
        ProgramSolution.objects.filter(program=program)
        .filter(Q(captain=user) | Q(members__user=user))
        .distinct()
        .order_by("created_at", "pk")[:2]
    )
    links = list(
        participant_project_links(program, user)
        .select_related("project")
        .order_by("pk")[:2]
    )
    if len(solutions) + len(links) > 1:
        raise SolutionError(
            "ambiguous_application", "Связи заявок требуют проверки организатором."
        )
    if solutions:
        obj = solutions[0]
        return dict(
            kind="solution", program_id=program.pk, solution_id=obj.pk, name=obj.name
        )
    if links:
        obj = links[0]
        return dict(
            kind="legacy_project",
            program_id=program.pk,
            project_id=obj.project_id,
            program_link_id=obj.pk,
            name=obj.project.name,
        )
    return None


def form_data(program):
    fields = [
        dict(
            id=f.pk,
            type=f.field_type,
            purpose="case" if f.name == "case" else f.purpose,
            label=f.label,
            help_text=f.help_text or "",
            required=f.is_required,
            position=f.position,
            options=f.get_options_list(),
            validation={
                key: f.validation.get(key, default)
                for key, default in VALIDATION_DEFAULTS.items()
            },
        )
        for f in program.fields.order_by("position", "pk")
    ]
    definition = dict(template=program.solution_template, fields=fields)
    revision = hashlib.sha256(
        json.dumps(
            definition, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    configured = program.solution_template in ("case_championship", "hackathon") and any(
        f["purpose"] == "case"
        and f["type"] == "select"
        and f["required"]
        and f["options"]
        for f in fields
    )
    return dict(
        program_id=program.pk,
        revision=revision,
        template=program.solution_template,
        is_configured=bool(configured),
        is_snapshot=False,
        fields=fields,
    )


def context_data(program, user):
    application = current_application(program, user)
    registered = PartnerProgramUserProfile.objects.filter(
        partner_program=program, user=user
    ).exists()
    reason = None
    if application:
        reason = "already_has_application"
    elif program.solution_storage_mode != "solution":
        reason = "legacy_mode"
    elif not (registered or program.is_manager(user)):
        reason = "not_program_member"
    elif not program.is_project_submission_open():
        reason = "submission_closed"
    elif not form_data(program)["is_configured"]:
        reason = "form_not_configured"
    return dict(
        program_id=program.pk,
        storage_mode=program.solution_storage_mode,
        is_registered=registered,
        is_competitive=program.is_competitive,
        submission_open=program.is_project_submission_open(),
        submission_deadline=iso(program.get_project_submission_deadline()),
        can_create=reason is None,
        blocked_reason=reason,
        current_application=application,
    )


def visible_solutions(program, user):
    query = ProgramSolution.objects.filter(program=program)
    # Экспертные назначения и публикация подключаются в BE07/BE08; до этого закрыты.
    if can_manage_program(user, program):
        return query
    return query.filter(Q(captain=user) | Q(members__user=user)).distinct()


def solution_data(solution, user):
    program = solution.program
    members = list(solution.members.select_related("user"))
    accepted = {m.user_id for m in members}
    pending = set(
        solution.invitations.filter(status="pending").values_list(
            "recipient_id", flat=True
        )
    )
    own = solution.captain_id == user.pk or user.pk in accepted
    submitted = solution.status == "submitted"
    form = form_data(program)
    answers = [
        dict(field_id=a.field_id, value=a.value)
        for a in solution.answers.order_by("field_id")
    ]
    name, captain_id = solution.name, solution.captain_id
    member_data = [
        dict(
            user=user_data(m.user),
            role=m.role,
            specialization=m.specialization,
            joined_at=iso(m.joined_at),
            is_captain=m.user_id == captain_id,
        )
        for m in members
    ]
    snapshot = solution.submission_snapshot
    if submitted and snapshot:
        name, captain_id = snapshot["name"], snapshot["captain_id"]
        form, answers, member_data = (
            snapshot["form"],
            snapshot["answers"],
            snapshot["members"],
        )
        accepted = {member["user"]["id"] for member in member_data}
    problems = []
    if program.is_competitive and own:
        if not name.strip():
            problems.append(issue("name", "required", "Укажите название решения."))
        if program.legacy_team_min_size and len(accepted) < program.legacy_team_min_size:
            problems.append(
                issue(
                    "team", "team_min_size", "В команде недостаточно принятых участников."
                )
            )
        if program.legacy_team_max_size and len(accepted) > program.legacy_team_max_size:
            problems.append(
                issue("team", "team_max_size", "Превышен максимальный размер команды.")
            )
        values = {a["field_id"]: a["value"] for a in answers}
        for field in form["fields"]:
            value = values.get(field["id"])
            if field["required"] and (
                value is None or isinstance(value, str) and not value.strip()
            ):
                problems.append(
                    issue(
                        f"answers.{field['id']}",
                        "required",
                        "Заполните обязательное поле.",
                        field["id"],
                    )
                )
    return dict(
        id=solution.pk,
        program_id=program.pk,
        version=solution.version,
        name=name,
        captain_id=captain_id,
        created_at=iso(solution.created_at),
        updated_at=iso(solution.updated_at),
        team=dict(
            members=member_data,
            accepted_count=len(accepted),
            pending_count=len(pending),
            reserved_count=len(accepted | pending),
            min_size=program.legacy_team_min_size,
            max_size=program.legacy_team_max_size,
            is_frozen=submitted,
        ),
        form=form,
        answers=answers,
        submission=dict(
            required=program.is_competitive,
            status=solution.status,
            submission_open=program.is_project_submission_open(),
            deadline=iso(program.get_project_submission_deadline()),
            submitted_at=iso(solution.submitted_at),
        ),
        # BE01 не публикует еще не реализованные команды BE02–BE06.
        permissions=dict(
            can_edit=False, can_manage_team=False, can_invite=False, can_submit=False
        ),
        readiness=dict(is_ready=not problems, issues=problems)
        if program.is_competitive and own
        else None,
    )


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = sorted(set(data) - set(self.fields))
            if unknown:
                raise ValidationError({key: "Неизвестное поле." for key in unknown})
        return super().to_internal_value(data)


class NameField(serializers.CharField):
    def to_internal_value(self, value):
        if not isinstance(value, str):
            self.fail("invalid")
        return super().to_internal_value(value)


class CreateSolutionSerializer(StrictSerializer):
    name = NameField(required=False, min_length=1, max_length=256, trim_whitespace=False)


class SolutionListQuery(StrictSerializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)
    search = serializers.CharField(required=False, allow_blank=True)
    submission = serializers.ChoiceField(
        choices=["all", "submitted", "not_submitted"], default="all"
    )


@transaction.atomic
def create_solution(program_id, user, data):
    program = program_for(program_id, lock=True)
    if program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует заявки на основе проектов."
        )
    current = current_application(program, user)
    if current:
        if current["kind"] == "solution":
            existing = ProgramSolution.objects.get(pk=current["solution_id"])
            if existing.captain_id == user.pk:
                return existing, False
        raise SolutionError(
            "already_in_program_team", "У вас уже есть заявка команды в этой программе."
        )
    # Same registration/manager exception as legacy project_apply; C00 checks rights first.
    if not (
        program.is_manager(user)
        or PartnerProgramUserProfile.objects.filter(
            partner_program=program, user=user
        ).exists()
    ):
        raise SolutionError(
            "not_program_member",
            "Создание заявки доступно участникам программы.",
            status=403,
        )
    if not program.is_project_submission_open():
        raise SolutionError("submission_closed", "Срок создания заявок завершен.")
    if not form_data(program)["is_configured"]:
        raise SolutionError(
            "form_not_configured", "Организатор еще не настроил форму решения."
        )
    solution = ProgramSolution.objects.create(program=program, captain=user, **data)
    ProgramSolutionMember.objects.create(solution=solution, user=user)
    return solution, True


class SolutionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def handle_exception(self, exc):
        if isinstance(exc, SolutionError):
            return Response(exc.payload, status=exc.status_code)
        if isinstance(exc, Http404):
            return Response(
                dict(
                    code="not_found",
                    detail="Решение или программа не найдены.",
                    errors=[],
                    meta={},
                ),
                status=404,
            )
        if isinstance(exc, APIException):
            errors = []
            if isinstance(exc, ValidationError) and isinstance(exc.detail, dict):
                errors = [
                    issue(
                        key,
                        "invalid",
                        str(value[0] if isinstance(value, list) else value),
                    )
                    for key, value in exc.detail.items()
                ]
            code = (
                "validation_error"
                if isinstance(exc, ValidationError)
                else exc.default_code
            )
            if exc.status_code == 401:
                code = "authentication_required"
            detail = (
                "Проверьте данные запроса."
                if isinstance(exc, ValidationError)
                else str(exc.detail)
            )
            response = Response(
                dict(code=code, detail=detail, errors=errors, meta={}),
                status=exc.status_code,
            )
            if exc.status_code == 401:
                response["WWW-Authenticate"] = (
                    self.get_authenticate_header(self.request) or "Bearer"
                )
            return response
        return super().handle_exception(exc)


class SolutionContextView(SolutionAPIView):
    def get(self, request, pk):
        return Response(context_data(program_for(pk), request.user))


class SolutionListCreateView(SolutionAPIView):
    def get(self, request, pk):
        program = program_for(pk)
        query = SolutionListQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        if not program.is_competitive and data["submission"] != "all":
            raise ValidationError({"submission": "Фильтр сдачи неприменим."})
        rows = (
            visible_solutions(program, request.user)
            .select_related("captain")
            .order_by("created_at", "pk")
        )
        if data.get("search"):
            rows = rows.filter(name__icontains=data["search"])
        if data["submission"] != "all":
            rows = rows.filter(
                status="submitted" if data["submission"] == "submitted" else "draft"
            )
        offset, limit, total = data["offset"], data["limit"], rows.count()
        result = []
        for row in rows[offset : offset + limit]:  # noqa: E203 (black slice formatting)
            case = row.answers.filter(
                Q(field__purpose="case") | Q(field__name="case")
            ).first()
            name, captain = row.name, user_data(row.captain)
            accepted_count = row.members.count()
            case_value = case.value if case else None
            if row.status == "submitted" and row.submission_snapshot:
                snapshot = row.submission_snapshot
                name = snapshot["name"]
                accepted_count = len(snapshot["members"])
                captain = next(m["user"] for m in snapshot["members"] if m["is_captain"])
                case_ids = {
                    f["id"] for f in snapshot["form"]["fields"] if f["purpose"] == "case"
                }
                case_value = next(
                    (
                        a["value"]
                        for a in snapshot["answers"]
                        if a["field_id"] in case_ids
                    ),
                    None,
                )
            result.append(
                dict(
                    id=row.pk,
                    program_id=program.pk,
                    name=name,
                    captain=captain,
                    accepted_count=accepted_count,
                    case_value=case_value,
                    status=row.status,
                    submitted_at=iso(row.submitted_at),
                )
            )

        def link(start):
            params = request.query_params.copy()
            params["offset"], params["limit"] = start, limit
            return request.build_absolute_uri("?" + params.urlencode())

        return Response(
            dict(
                count=total,
                next=link(offset + limit) if offset + limit < total else None,
                previous=link(max(0, offset - limit)) if offset > 0 else None,
                results=result,
            )
        )

    def post(self, request, pk):
        serializer = CreateSolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj, created = create_solution(pk, request.user, serializer.validated_data)
        return Response(solution_data(obj, request.user), status=201 if created else 200)


class SolutionDetailView(SolutionAPIView):
    def get(self, request, pk, solution_id):
        program = program_for(pk)
        if not 0 < solution_id <= MAX_ID:
            raise Http404
        try:
            solution = (
                visible_solutions(program, request.user)
                .select_related("program")
                .get(pk=solution_id)
            )
        except ProgramSolution.DoesNotExist:
            raise Http404
        return Response(solution_data(solution, request.user))
