# Roadmap: DEV-072
# Повторяемый связанный набор данных для ручной проверки React-dev.

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from partner_programs.models import (
    Application,
    Evaluation,
    EvaluationScore,
    PartnerProgram,
    PartnerProgramUserProfile,
    Submission,
    SubmissionExpertAssignment,
    TeamMember,
)
from partner_programs.services.application_team import (
    create_or_get_application,
    submit_application,
)
from partner_programs.services.evaluations import (
    create_or_get_draft_evaluation,
    submit_evaluation,
    update_draft_evaluation,
)
from partner_programs.services.submission_assignments import (
    create_submission_assignment,
)
from project_rates.models import Criteria
from users.models import CustomUser, Expert, Member

User = get_user_model()

DEMO_PROGRAM_NAME = "[DEMO] Экспертная оценка React-dev"
DEMO_PROGRAM_TAG = "react-dev-expert-evaluation-demo"
DEMO_TEAM_NAME = "[DEMO] Команда React-dev"

DEMO_USER_SPECS = (
    {
        "key": "manager",
        "email": "demo.manager@procollab.test",
        "first_name": "Демо",
        "last_name": "Менеджер",
        "user_type": CustomUser.MEMBER,
    },
    {
        "key": "expert",
        "email": "demo.expert@procollab.test",
        "first_name": "Демо",
        "last_name": "Эксперт",
        "user_type": CustomUser.EXPERT,
    },
    {
        "key": "participant1",
        "email": "demo.participant1@procollab.test",
        "first_name": "Демо",
        "last_name": "Участник Один",
        "user_type": CustomUser.MEMBER,
    },
    {
        "key": "participant2",
        "email": "demo.participant2@procollab.test",
        "first_name": "Демо",
        "last_name": "Участник Два",
        "user_type": CustomUser.MEMBER,
    },
)

DEMO_CRITERION_SPECS = (
    {
        "name": "Полнота решения",
        "description": "Насколько полно раскрыта предлагаемая идея.",
        "type": "int",
        "min_value": 1,
        "max_value": 10,
    },
    {
        "name": "Проработанность",
        "description": "Качество проработки ключевых частей решения.",
        "type": "int",
        "min_value": 0,
        "max_value": 5,
    },
    {
        "name": "Реализуемость",
        "description": "Реалистичность плана и доступность ресурсов.",
        "type": "float",
        "min_value": 0,
        "max_value": 10,
    },
)

DEMO_SUBMISSION_SPECS = (
    {
        "key": "none",
        "stage_key": "demo-without-evaluation",
        "title": "[DEMO] Решение без оценки",
        "description": (
            "Демонстрационное решение для проверки начала оценивания.\n"
            "Описание содержит перенос строки и не содержит персональных данных."
        ),
        "links": [
            "https://example.com/react-dev-demo/without-evaluation",
            "javascript:alert('demo-link')",
        ],
    },
    {
        "key": "draft",
        "stage_key": "demo-draft-evaluation",
        "title": "[DEMO] Решение с черновиком",
        "description": (
            "Демонстрационное решение с частично заполненной оценкой.\n"
            "Подходит для проверки восстановления формы и autosave."
        ),
        "links": [
            "https://example.com/react-dev-demo/draft",
            {"invalid": "nested payload"},
        ],
    },
    {
        "key": "submitted",
        "stage_key": "demo-submitted-evaluation",
        "title": "[DEMO] Решение с отправленной оценкой",
        "description": (
            "Демонстрационное решение с окончательно отправленной оценкой.\n"
            "Используется для проверки read-only состояния."
        ),
        "links": ["https://example.com/react-dev-demo/submitted"],
    },
)


class ReactDevDemoDataError(Exception):
    """Команда не может безопасно создать или обновить заданный DEMO-контур."""


@dataclass(frozen=True)
class ReactDevDemoSummary:
    users: int
    programs: int
    program_memberships: int
    applications: int
    teams: int
    team_members: int
    criteria: int
    submissions: int
    assignments: int
    evaluations: int
    scores: int

    def as_dict(self):
        return {
            "users": self.users,
            "programs": self.programs,
            "program_memberships": self.program_memberships,
            "applications": self.applications,
            "teams": self.teams,
            "team_members": self.team_members,
            "criteria": self.criteria,
            "submissions": self.submissions,
            "assignments": self.assignments,
            "evaluations": self.evaluations,
            "scores": self.scores,
        }


def _find_owned_program():
    candidates = list(
        PartnerProgram.objects.filter(
            Q(name=DEMO_PROGRAM_NAME) | Q(tag=DEMO_PROGRAM_TAG)
        ).order_by("pk")
    )
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ReactDevDemoDataError(
            "Идентификаторы DEMO-программы соответствуют нескольким программам; "
            "требуется ручная проверка."
        )
    program = candidates[0]
    if program.name != DEMO_PROGRAM_NAME or program.tag != DEMO_PROGRAM_TAG:
        raise ReactDevDemoDataError(
            "Название или тег DEMO-программы уже используется другой программой."
        )
    return program


def _delete_owned_program():
    program = _find_owned_program()
    if program is not None:
        # EvaluationScore защищает Criteria, поэтому сначала удаляем точный
        # evaluation-граф программы, а затем запускаем каскад Program.
        Evaluation.objects.filter(submission__program=program).delete()
        SubmissionExpertAssignment.objects.filter(submission__program=program).delete()
        program.delete()


def _ensure_user(spec, password):
    user, _created = User.objects.get_or_create(
        email=spec["email"],
        defaults={
            "first_name": spec["first_name"],
            "last_name": spec["last_name"],
            "birthday": date(1990, 1, 1),
            "is_active": True,
            "user_type": spec["user_type"],
        },
    )
    user.first_name = spec["first_name"]
    user.last_name = spec["last_name"]
    user.birthday = date(1990, 1, 1)
    user.is_active = True
    user.is_staff = False
    user.is_superuser = False
    user.user_type = spec["user_type"]
    user.set_password(password)
    user.save(
        update_fields=[
            "first_name",
            "last_name",
            "birthday",
            "is_active",
            "is_staff",
            "is_superuser",
            "user_type",
            "password",
        ]
    )

    if spec["user_type"] == CustomUser.EXPERT:
        Expert.objects.get_or_create(user=user)
    else:
        Member.objects.get_or_create(user=user)
    return user


def _ensure_program():
    program = _find_owned_program()
    now = timezone.now()
    values = {
        "name": DEMO_PROGRAM_NAME,
        "tag": DEMO_PROGRAM_TAG,
        "description": (
            "Связанный демонстрационный контур для smoke-тестирования "
            "кабинета эксперта React-dev."
        ),
        "city": "Москва",
        "data_schema": {},
        "draft": False,
        "is_competitive": True,
        "projects_availability": "experts_only",
        "participation_format": PartnerProgram.PARTICIPATION_FORMAT_TEAM_ONLY,
        "team_min_size": 2,
        "team_max_size": 4,
        "datetime_registration_ends": now + timezone.timedelta(days=180),
        "datetime_application_ends": now + timezone.timedelta(days=180),
        "datetime_project_submission_ends": now + timezone.timedelta(days=180),
        "datetime_evaluation_ends": now + timezone.timedelta(days=180),
        "datetime_started": now - timezone.timedelta(days=1),
        "datetime_finished": now + timezone.timedelta(days=180),
    }
    if program is None:
        return PartnerProgram.objects.create(**values)

    for field, value in values.items():
        setattr(program, field, value)
    program.save(update_fields=[*values, "datetime_updated"])
    return program


def _ensure_membership(program, user):
    membership, _created = PartnerProgramUserProfile.objects.update_or_create(
        partner_program=program,
        user=user,
        defaults={
            "project": None,
            "partner_program_data": {"demo_seed": "DEV-072"},
        },
    )
    return membership


def _ensure_application(program, users):
    result = create_or_get_application(
        program=program,
        user=users["participant1"],
        created_by=users["participant1"],
        participation_mode=Application.PARTICIPATION_MODE_TEAM,
        form_data={"demo_seed": "DEV-072"},
        team_name=DEMO_TEAM_NAME,
    )
    application = result.application
    team = application.team
    TeamMember.objects.update_or_create(
        team=team,
        user=users["participant2"],
        defaults={
            "role": TeamMember.ROLE_MEMBER,
            "status": TeamMember.STATUS_ACCEPTED,
            "invited_by": users["participant1"],
        },
    )
    return submit_application(
        application=application,
        actor=users["participant1"],
    )


def _ensure_criteria(program):
    criteria = {}
    for spec in DEMO_CRITERION_SPECS:
        criterion, _created = Criteria.objects.update_or_create(
            partner_program=program,
            name=spec["name"],
            defaults={
                "description": spec["description"],
                "type": spec["type"],
                "min_value": spec["min_value"],
                "max_value": spec["max_value"],
            },
        )
        criteria[spec["name"]] = criterion

    expected_ids = [criterion.pk for criterion in criteria.values()]
    EvaluationScore.objects.filter(
        evaluation__submission__program=program,
    ).exclude(criterion_id__in=expected_ids).delete()
    Criteria.objects.filter(partner_program=program).exclude(pk__in=expected_ids).delete()
    return criteria


def _ensure_submissions(application):
    submissions = {}
    for spec in DEMO_SUBMISSION_SPECS:
        submission, _created = Submission.objects.update_or_create(
            application=application,
            stage_key=spec["stage_key"],
            version=1,
            defaults={
                "program": application.program,
                "submitted_by": application.user,
                "title": spec["title"],
                "description": spec["description"],
                "form_data": {"demo_seed": "DEV-072", "private": True},
                "links": spec["links"],
                "status": Submission.STATUS_FINAL,
                "submitted_at": timezone.now(),
            },
        )
        submissions[spec["key"]] = submission
    return submissions


def _active_assignment(submission, expert):
    return (
        SubmissionExpertAssignment.objects.filter(
            submission=submission,
            expert=expert,
            status__in=SubmissionExpertAssignment.ACTIVE_STATUSES,
        )
        .order_by("-created_at", "-pk")
        .first()
    )


def _ensure_assignment(submission, expert, manager):
    assignment = _active_assignment(submission, expert)
    if assignment is None:
        assignment = create_submission_assignment(
            program=submission.program,
            submission_id=submission.pk,
            expert_id=expert.pk,
            actor=manager,
        ).assignment
    return assignment


def _set_assignment_assigned(assignment):
    if assignment.status == SubmissionExpertAssignment.STATUS_ASSIGNED:
        return assignment
    assignment.status = SubmissionExpertAssignment.STATUS_ASSIGNED
    assignment.completed_at = None
    assignment.save(
        update_fields=[
            "status",
            "completed_at",
            "updated_at",
        ]
    )
    return assignment


def _sync_evaluation_scores(evaluation, criteria, values):
    expected = {
        criteria[name].pk: (criteria[name], Decimal(value)) for name, value in values
    }
    existing = {
        score.criterion_id: score
        for score in evaluation.scores.select_related("criterion")
    }

    for criterion_id, (criterion, value) in expected.items():
        score = existing.get(criterion_id)
        if score is None:
            EvaluationScore.objects.create(
                evaluation=evaluation,
                criterion=criterion,
                value=value,
            )
        elif score.value != value:
            score.value = value
            score.save(update_fields=["value", "updated_at"])

    evaluation.scores.exclude(criterion_id__in=expected).delete()


def _ensure_draft_evaluation_state(evaluation, expert_user, comment):
    if evaluation.status == Evaluation.STATUS_SUBMITTED:
        evaluation.status = Evaluation.STATUS_DRAFT
        evaluation.submitted_at = None
        evaluation.total_score = None
        evaluation.save(
            update_fields=[
                "status",
                "submitted_at",
                "total_score",
                "updated_at",
            ]
        )
    if evaluation.comment != comment:
        update_draft_evaluation(
            evaluation_id=evaluation.pk,
            user=expert_user,
            comment_supplied=True,
            comment=comment,
        )
        evaluation.comment = comment


def _ensure_evaluation_states(submissions, criteria, expert_user, manager):
    expert = expert_user.expert
    assignments = {
        key: _ensure_assignment(submission, expert, manager)
        for key, submission in submissions.items()
    }

    Evaluation.objects.filter(
        submission=submissions["none"],
        expert=expert,
    ).delete()
    _set_assignment_assigned(assignments["none"])

    draft_evaluation = Evaluation.objects.filter(
        submission=submissions["draft"],
        expert=expert,
    ).first()
    _set_assignment_assigned(assignments["draft"])
    if draft_evaluation is None:
        draft_evaluation = create_or_get_draft_evaluation(
            submission_id=submissions["draft"].pk,
            user=expert_user,
        ).evaluation
    _ensure_draft_evaluation_state(
        draft_evaluation,
        expert_user,
        "Частично заполненный демонстрационный черновик.",
    )
    _sync_evaluation_scores(
        draft_evaluation,
        criteria,
        (("Полнота решения", "7"),),
    )

    submitted_values = (
        ("Полнота решения", "9"),
        ("Проработанность", "4"),
        ("Реализуемость", "7.5"),
    )
    submitted_evaluation = Evaluation.objects.filter(
        submission=submissions["submitted"],
        expert=expert,
    ).first()
    if submitted_evaluation is None:
        _set_assignment_assigned(assignments["submitted"])
        submitted_evaluation = create_or_get_draft_evaluation(
            submission_id=submissions["submitted"].pk,
            user=expert_user,
        ).evaluation
    if submitted_evaluation.status == Evaluation.STATUS_DRAFT:
        _set_assignment_assigned(assignments["submitted"])
        _ensure_draft_evaluation_state(
            submitted_evaluation,
            expert_user,
            "Итоговая демонстрационная оценка.",
        )
        _sync_evaluation_scores(
            submitted_evaluation,
            criteria,
            submitted_values,
        )
        submit_evaluation(
            evaluation_id=submitted_evaluation.pk,
            user=expert_user,
        )
    else:
        if submitted_evaluation.comment != "Итоговая демонстрационная оценка.":
            submitted_evaluation.comment = "Итоговая демонстрационная оценка."
            submitted_evaluation.save(update_fields=["comment", "updated_at"])
        _sync_evaluation_scores(
            submitted_evaluation,
            criteria,
            submitted_values,
        )
        if assignments["submitted"].status != SubmissionExpertAssignment.STATUS_COMPLETED:
            assignments["submitted"].status = SubmissionExpertAssignment.STATUS_COMPLETED
            assignments["submitted"].completed_at = submitted_evaluation.submitted_at
            assignments["submitted"].save(
                update_fields=[
                    "status",
                    "completed_at",
                    "updated_at",
                ]
            )


def _summary(program):
    application_qs = Application.objects.filter(program=program)
    submission_qs = Submission.objects.filter(program=program)
    evaluation_qs = Evaluation.objects.filter(submission__program=program)
    return ReactDevDemoSummary(
        users=User.objects.filter(
            email__in=[spec["email"] for spec in DEMO_USER_SPECS]
        ).count(),
        programs=PartnerProgram.objects.filter(pk=program.pk).count(),
        program_memberships=PartnerProgramUserProfile.objects.filter(
            partner_program=program
        ).count(),
        applications=application_qs.count(),
        teams=application_qs.filter(team__isnull=False).count(),
        team_members=TeamMember.objects.filter(
            team__application__program=program
        ).count(),
        criteria=Criteria.objects.filter(partner_program=program).count(),
        submissions=submission_qs.count(),
        assignments=SubmissionExpertAssignment.objects.filter(
            submission__program=program,
            status__in=SubmissionExpertAssignment.ACTIVE_STATUSES,
        ).count(),
        evaluations=evaluation_qs.count(),
        scores=EvaluationScore.objects.filter(
            evaluation__submission__program=program
        ).count(),
    )


def build_react_dev_demo_data(*, password, reset=False, dry_run=False):
    """Создать полный набор DEV-072 и при необходимости откатить изменения."""

    with transaction.atomic():
        if reset:
            _delete_owned_program()

        users = {spec["key"]: _ensure_user(spec, password) for spec in DEMO_USER_SPECS}
        program = _ensure_program()
        program.managers.set([users["manager"]])
        expert = users["expert"].expert
        expert.programs.add(program)

        for user in users.values():
            _ensure_membership(program, user)

        application = _ensure_application(program, users)
        criteria = _ensure_criteria(program)
        submissions = _ensure_submissions(application)
        _ensure_evaluation_states(
            submissions,
            criteria,
            users["expert"],
            users["manager"],
        )
        summary = _summary(program)

        if dry_run:
            transaction.set_rollback(True)
        return summary
