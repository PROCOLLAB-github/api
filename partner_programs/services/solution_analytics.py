"""Scoped read models for solution analytics; no Project projection or writes."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Prefetch
from django.db.models.functions import TruncDate
from django.utils import timezone

from partner_programs.models import PartnerProgramUserProfile
from partner_programs.services.analytics import (
    ACTIVITY_DAYS,
    _get_participant_metrics,
    _get_participant_regions,
)
from partner_programs.services.assignment_analytics import build_delayed_experts
from partner_programs.services.solution_case_analytics import (
    build_solution_case_analytics,
)
from partner_programs.solution_api import iso
from partner_programs.solution_models import ProgramSolution, ProgramSolutionMember
from partner_programs.solution_schema import empty_value, form_data
from project_rates.evaluation_math import complete_values
from project_rates.models import Criteria
from project_rates.solution_evaluation import snapshot_case, snapshot_name
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore


class SolutionAnalyticsContext:
    def __init__(self, program, *, now=None, solution_ids=None):
        self.program = program
        self.now = now if now is not None else timezone.now()
        self.form = form_data(program)
        self.case_field = next(
            (field for field in self.form["fields"] if field["purpose"] == "case"), None
        )
        self.options = self.case_field["options"] if self.case_field else []
        query = ProgramSolution.objects.filter(program=program)
        if solution_ids is not None:
            query = query.filter(pk__in=solution_ids)
        self.solutions = list(
            query.select_related("captain")
            .prefetch_related(
                "answers",
                Prefetch(
                    "members",
                    queryset=ProgramSolutionMember.objects.select_related("user"),
                ),
            )
            .order_by("created_at", "pk")
        )
        self.by_id = {solution.pk: solution for solution in self.solutions}
        self.criteria = list(
            Criteria.objects.filter(partner_program=program).order_by("pk")
        )
        self.score_records = list(
            SolutionScore.objects.filter(
                solution_id__in=self.by_id, criteria__partner_program=program
            )
            .order_by("solution_id", "user_id", "criteria_id")
            .values(
                "pk",
                "solution_id",
                "user_id",
                "criteria_id",
                "value",
                "user__first_name",
                "user__last_name",
                "user__patronymic",
            )
        )
        self.values = defaultdict(lambda: defaultdict(dict))
        for score in self.score_records:
            self.values[score["solution_id"]][score["user_id"]][
                score["criteria_id"]
            ] = score["value"]
        self.assignments = [
            self.assignment(row)
            for row in SolutionExpertAssignment.objects.filter(
                partner_program=program, solution_id__in=self.by_id
            )
            .select_related("expert__user")
            .order_by("pk")
        ]
        self.assignments_by_solution = defaultdict(list)
        for row in self.assignments:
            self.assignments_by_solution[row["application"]["solution_id"]].append(row)

    def application(self, solution):
        return dict(
            kind="solution",
            program_id=self.program.pk,
            solution_id=solution.pk,
            name=snapshot_name(solution),
        )

    def case_name(self, solution):
        value = snapshot_case(
            solution, draft_field_id=self.case_field["id"] if self.case_field else None
        )
        return value if value in self.options else None

    def assignment(self, row):
        solution = self.by_id[row.solution_id]
        submitted = solution.status == "submitted"
        own = self.values[solution.pk][row.expert.user_id]
        status = (
            "not_ready"
            if not submitted
            else "completed"
            if complete_values(self.criteria, own)
            else "in_progress"
            if self.criteria and own
            else "pending"
        )
        waiting = (
            max(solution.submitted_at, row.datetime_created)
            if status in ("pending", "in_progress") and solution.submitted_at is not None
            else None
        )
        user = row.expert.user
        return dict(
            assignment_id=row.pk,
            expert=dict(
                expert_id=row.expert_id,
                user_id=user.pk,
                first_name=user.first_name,
                last_name=user.last_name,
                full_name=" ".join(filter(None, (user.first_name, user.last_name))),
                avatar=user.avatar or None,
            ),
            application=self.application(solution),
            status=status,
            assigned_at=row.datetime_created,
            submitted=submitted,
            submitted_at=solution.submitted_at if submitted else None,
            waiting_since=waiting,
            waiting_seconds=max(0, int((self.now - waiting).total_seconds()))
            if waiting
            else None,
        )

    def assignment_scores(self, assignment):
        values = self.values[assignment["application"]["solution_id"]][
            assignment["expert"]["user_id"]
        ]
        return [
            dict(
                criterion_id=criterion.pk,
                name=criterion.name,
                description=criterion.description,
                type=criterion.type,
                min_value=criterion.min_value,
                max_value=criterion.max_value,
                value=values.get(criterion.pk),
                is_scored=criterion.pk in values,
            )
            for criterion in self.criteria
        ]

    def state(self, solution):
        if not self.program.is_competitive:
            return "not_applicable"
        if solution.status != "submitted":
            return "not_submitted"
        if not self.program.is_distributed_evaluation:
            return "evaluated" if self.values[solution.pk] else "awaiting_evaluation"
        rows = self.assignments_by_solution[solution.pk]
        completed = sum(row["status"] == "completed" for row in rows)
        if not rows or not completed:
            return "awaiting_evaluation"
        required = self.program.required_evaluators or len(rows)
        return "partially_evaluated" if completed < required else "evaluated"

    def applied_form_and_answers(self, solution):
        if solution.status == "submitted":
            snapshot = solution.submission_snapshot or {}
            return snapshot.get("form", {}).get("fields", []), {
                row["field_id"]: row["value"] for row in snapshot.get("answers", [])
            }
        return self.form["fields"], {
            row.field_id: row.value for row in solution.answers.all()
        }

    def coverage(self):
        definitions = {field["id"]: field for field in self.form["fields"]}
        counts = defaultdict(
            lambda: dict(
                applicable=0, answered=0, required_applicable=0, required_unanswered=0
            )
        )
        for solution in self.solutions:
            fields, answers = self.applied_form_and_answers(solution)
            for field in fields:
                key = field["id"]
                definitions.setdefault(key, field)
                row = counts[key]
                present = not empty_value(answers.get(key))
                row["applicable"] += 1
                row["answered"] += int(present)
                row["required_applicable"] += int(field["required"])
                row["required_unanswered"] += int(field["required"] and not present)
        return [
            dict(
                field_id=field["id"],
                label=field["label"],
                type=field["type"],
                purpose=field["purpose"],
                **counts[key]
            )
            for key, field in definitions.items()
        ]

    def team(self, solution):
        if solution.status == "submitted":
            return (solution.submission_snapshot or {}).get("members", [])
        captain = solution.captain
        return [
            dict(
                user=dict(
                    id=captain.pk,
                    first_name=captain.first_name,
                    last_name=captain.last_name,
                    avatar_url=captain.avatar or None,
                ),
                role="Капитан",
                is_captain=True,
            ),
            *[
                dict(
                    user=dict(
                        id=m.user_id,
                        first_name=m.user.first_name,
                        last_name=m.user.last_name,
                        avatar_url=m.user.avatar or None,
                    ),
                    role=m.role,
                    is_captain=False,
                )
                for m in solution.members.all()
            ],
        ]

    def solution_row(self, solution):
        captain = next(row["user"] for row in self.team(solution) if row["is_captain"])
        state = self.state(solution)
        applicable = (
            self.program.is_competitive and self.program.is_distributed_evaluation
        )
        assignments = self.assignments_by_solution[solution.pk]
        total = len(assignments) if applicable else None
        completed = (
            sum(row["status"] == "completed" for row in assignments)
            if applicable
            else None
        )
        reason = None
        if state in ("awaiting_evaluation", "partially_evaluated"):
            reason = (
                "awaiting_first_evaluation"
                if total is None
                else "no_assignments"
                if total == 0
                else "no_completed_evaluations"
                if completed == 0
                else "partially_evaluated"
            )
        return dict(
            application=self.application(solution),
            captain=dict(
                user_id=captain["id"],
                full_name=" ".join(
                    filter(None, (captain["first_name"], captain["last_name"]))
                ),
                avatar=captain.get("avatar_url"),
            ),
            case_name=self.case_name(solution),
            submission_status=solution.status,
            evaluation_status=state,
            created_at=iso(solution.created_at),
            submitted_at=iso(solution.submitted_at),
            assignments_total=total,
            assignments_completed=completed,
            waiting_reason=reason,
        )

    def overview(self):
        program = self.program
        participants = _get_participant_metrics(program.pk)
        regions = _get_participant_regions(program.pk)
        competitive = program.is_competitive
        states = [self.state(solution) for solution in self.solutions]
        submitted = sum(solution.status == "submitted" for solution in self.solutions)
        completed = sum(row["status"] == "completed" for row in self.assignments)
        return dict(
            program_id=program.pk,
            summary=dict(
                participants=dict(total=participants["unique_participants"]),
                solutions=dict(total=len(self.solutions)),
                experts=dict(total=program.experts.count()),
                participant_regions=dict(total=len(regions), items=regions),
            ),
            participant_funnel=dict(
                **{
                    key: participants[key]
                    for key in (
                        "registrations",
                        "unique_participants",
                        "visited_participants",
                        "onboarded_participants",
                        "with_team",
                    )
                },
                captains=participants["project_creators"],
                submitted_captains=participants["submitted_project_creators"]
                if competitive
                else None
            ),
            solution_funnel=dict(
                created=len(self.solutions),
                submission_applicable=competitive,
                not_submitted=len(self.solutions) - submitted if competitive else None,
                submitted=submitted if competitive else None,
                evaluated=states.count("evaluated") if competitive else None,
            ),
            evaluation_status=dict(
                applicable=competitive,
                mode="distributed" if program.is_distributed_evaluation else "open",
                required_evaluators=program.required_evaluators,
                max_evaluations_per_solution=program.max_project_rates,
                assignments=dict(
                    total=len(self.assignments),
                    pending=len(self.assignments) - completed,
                    evaluated=completed,
                )
                if competitive and program.is_distributed_evaluation
                else None,
                solutions=dict(
                    submitted=submitted,
                    awaiting_evaluation=states.count("awaiting_evaluation"),
                    partially_evaluated=states.count("partially_evaluated"),
                    evaluated=states.count("evaluated"),
                )
                if competitive
                else None,
            ),
            attention=dict(
                participants_without_visit=participants["without_visit"],
                participants_without_onboarding=participants["without_onboarding"],
                participants_without_team=participants["without_team"],
                solutions_awaiting_evaluation=sum(
                    state in ("awaiting_evaluation", "partially_evaluated")
                    for state in states
                )
                if competitive
                else None,
                solutions_not_submitted=len(self.solutions) - submitted
                if competitive
                else None,
                delayed_experts=build_delayed_experts(
                    self.assignments,
                    evaluation_ends=program.datetime_evaluation_ends,
                    now=self.now,
                )
                if competitive and program.is_distributed_evaluation
                else dict(total=0, items=[]),
            ),
            activity=solution_activity(program),
            cases=build_solution_case_analytics(program),
            field_coverage=self.coverage(),
        )


def solution_activity(program):
    today = timezone.localdate()
    start = today - timedelta(days=ACTIVITY_DAYS - 1)
    registrations = dict(
        PartnerProgramUserProfile.objects.filter(
            partner_program=program,
            datetime_created__date__gte=start,
            datetime_created__date__lte=today,
        )
        .annotate(day=TruncDate("datetime_created"))
        .values("day")
        .annotate(total=Count("pk"))
        .values_list("day", "total")
    )
    submissions = (
        dict(
            ProgramSolution.objects.filter(
                program=program,
                status="submitted",
                submitted_at__date__gte=start,
                submitted_at__date__lte=today,
            )
            .annotate(day=TruncDate("submitted_at"))
            .values("day")
            .annotate(total=Count("pk"))
            .values_list("day", "total")
        )
        if program.is_competitive
        else {}
    )
    return [
        dict(
            date=day.isoformat(),
            registrations=registrations.get(day, 0),
            submitted_solutions=submissions.get(day, 0)
            if program.is_competitive
            else None,
        )
        for day in (start + timedelta(days=offset) for offset in range(ACTIVITY_DAYS))
    ]
