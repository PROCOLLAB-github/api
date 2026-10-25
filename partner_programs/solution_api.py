"""C00: контекст, создание, чтение и команды состава решения."""

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from rest_framework import serializers
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.models import PartnerProgramUserProfile
from partner_programs.services.role_analytics import participant_project_links
from partner_programs.solution_models import ProgramSolution, ProgramSolutionMember
from partner_programs.solution_errors import MAX_ID, SolutionError, issue
from partner_programs.solution_schema import form_data
from partner_programs.solution_submission import readiness_issues
from partner_programs import solution_team
from partner_programs.solution_team import program_for, visible_solutions


def iso(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def user_data(user):
    return dict(
        id=user.pk,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar or None,
    )


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
    elif not program.solution_creation_enabled:
        reason = "solution_creation_disabled"
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


def participation_data(solution):
    return dict(
        status="archived" if solution.archived_at else "active",
        archived_at=iso(solution.archived_at),
        reason=solution.archive_reason,
    )


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
    archived = solution.archived_at is not None
    frozen = submitted or archived
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
    snapshot = solution.archive_snapshot if archived else solution.submission_snapshot
    if frozen and snapshot:
        name, captain_id = snapshot["name"], snapshot["captain_id"]
        form, answers, member_data = (
            snapshot["form"],
            snapshot["answers"],
            snapshot["members"],
        )
        accepted = {member["user"]["id"] for member in member_data}
    problems = []
    if archived:
        problems = [
            issue("participation", "solution_archived", "Решение снято с участия.")
        ]
    elif program.is_competitive and own and not submitted:
        problems = readiness_issues(solution, form, answers, accepted)
    return dict(
        id=solution.pk,
        program_id=program.pk,
        version=solution.version,
        name=name,
        captain_id=captain_id,
        created_at=iso(solution.created_at),
        updated_at=iso(solution.updated_at),
        participation=participation_data(solution),
        team=dict(
            members=member_data,
            accepted_count=len(accepted),
            pending_count=len(pending),
            reserved_count=len(accepted | pending),
            min_size=program.legacy_team_min_size,
            max_size=program.legacy_team_max_size,
            is_frozen=frozen,
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
        permissions=dict(
            can_edit=(
                solution.captain_id == user.pk
                and program.solution_storage_mode == "solution"
                and not frozen
            ),
            can_manage_team=(
                solution.captain_id == user.pk
                and program.solution_storage_mode == "solution"
                and not frozen
            ),
            can_invite=(
                solution.captain_id == user.pk
                and program.solution_storage_mode == "solution"
                and not frozen
            ),
            can_submit=(
                solution.captain_id == user.pk
                and program.solution_storage_mode == "solution"
                and not frozen
                and program.is_competitive
                and program.is_project_submission_open()
            ),
            can_leave=(
                user.pk in accepted
                and solution.captain_id != user.pk
                and program.solution_storage_mode == "solution"
                and not frozen
            ),
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


class CommandInteger(serializers.IntegerField):
    def to_internal_value(self, value):
        if isinstance(value, bool) or not isinstance(value, int):
            self.fail("invalid")
        return super().to_internal_value(value)


class TeamCommandSerializer(StrictSerializer):
    expected_solution_version = CommandInteger(min_value=1)


class CaptainCommandSerializer(TeamCommandSerializer):
    new_captain_user_id = CommandInteger(min_value=1, max_value=MAX_ID)


class TeamVersionQuery(StrictSerializer):
    expected_solution_version = serializers.RegexField(r"^[1-9][0-9]*$")


def mutation_receipt(solution):
    return dict(
        solution_id=solution.pk,
        solution_version=solution.version,
        updated_at=iso(solution.updated_at),
    )


class SolutionListQuery(StrictSerializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)
    search = serializers.CharField(required=False, allow_blank=True)
    participation = serializers.ChoiceField(
        choices=["active", "archived", "all"], default="active"
    )
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
    if not program.solution_creation_enabled:
        raise SolutionError(
            "solution_creation_disabled",
            "Создание новых решений временно приостановлено. "
            "Ранее созданные заявки доступны.",
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
            visible_solutions(
                program, request.user, include_archived=data["participation"] != "active"
            )
            .select_related("captain")
            .order_by("created_at", "pk")
        )
        if data["participation"] == "archived":
            rows = rows.filter(archived_at__isnull=False)
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
            snapshot = (
                row.archive_snapshot if row.archived_at else row.submission_snapshot
            )
            if snapshot and (row.status == "submitted" or row.archived_at):
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
                    participation=participation_data(row),
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
    def patch(self, request, pk, solution_id):
        from partner_programs.solution_answer_api import patch_solution

        return patch_solution(request, pk, solution_id)

    def get(self, request, pk, solution_id):
        program = program_for(pk)
        if not 0 < solution_id <= MAX_ID:
            raise Http404
        try:
            solution = (
                visible_solutions(program, request.user, include_archived=True)
                .select_related("program")
                .get(pk=solution_id)
            )
        except ProgramSolution.DoesNotExist:
            raise Http404
        return Response(solution_data(solution, request.user))


class SolutionMemberView(SolutionAPIView):
    def delete(self, request, pk, solution_id, user_id):
        query = TeamVersionQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        if request.data:
            raise ValidationError({"body": "Передайте версию в параметрах запроса."})
        solution = solution_team.remove_member(
            program_id=pk,
            solution_id=solution_id,
            user_id=user_id,
            actor=request.user,
            expected_version=query.validated_data["expected_solution_version"],
        )
        return Response(mutation_receipt(solution))


class SolutionLeaveView(SolutionAPIView):
    def post(self, request, pk, solution_id):
        query = StrictSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        serializer = TeamCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        solution_team.leave_team(
            program_id=pk,
            solution_id=solution_id,
            actor=request.user,
            expected_version=serializer.validated_data["expected_solution_version"],
        )
        return Response(status=204)


class SolutionCaptainView(SolutionAPIView):
    def post(self, request, pk, solution_id):
        query = StrictSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        serializer = CaptainCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        solution = solution_team.transfer_captain(
            program_id=pk,
            solution_id=solution_id,
            user_id=serializer.validated_data["new_captain_user_id"],
            actor=request.user,
            expected_version=serializer.validated_data["expected_solution_version"],
        )
        return Response(mutation_receipt(solution))
