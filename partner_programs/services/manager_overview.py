# Roadmap: DEV-076, DEV-056

from django.db.models import Count, Q

from partner_programs.models import (
    Application,
    Evaluation,
    PartnerProgram,
    PartnerProgramUserProfile,
    Submission,
    SubmissionExpertAssignment,
    Team,
    TeamMember,
)


def _choice_counts(metrics, prefix, choices):
    return {value: metrics[f"{prefix}_{value}"] for value, _label in choices}


def _count_by_choice(choices, field_name):
    return {
        f"{field_name}_{value}": Count(
            "id",
            filter=Q(**{field_name: value}),
        )
        for value, _label in choices
    }


def build_manager_program_overview(program: PartnerProgram) -> dict:
    """Возвращает обезличенные агрегаты этапов участия в одной программе."""
    registration_metrics = PartnerProgramUserProfile.objects.filter(
        partner_program=program
    ).aggregate(
        total=Count("id"),
        participants_total=Count(
            "user_id",
            filter=Q(user_id__isnull=False),
            distinct=True,
        ),
    )

    application_metrics = Application.objects.filter(program=program).aggregate(
        total=Count("id"),
        **_count_by_choice(Application.STATUS_CHOICES, "status"),
        **_count_by_choice(
            Application.PARTICIPATION_MODE_CHOICES,
            "participation_mode",
        ),
    )

    team_metrics = Team.objects.filter(application__program=program).aggregate(
        total=Count("id", distinct=True),
        accepted_members=Count(
            "members",
            filter=Q(members__status=TeamMember.STATUS_ACCEPTED),
            distinct=True,
        ),
    )

    submission_metrics = Submission.objects.filter(program=program).aggregate(
        total=Count("id"),
        applications_with_submitted_solution=Count(
            "application_id",
            filter=Q(
                status__in=(
                    Submission.STATUS_SUBMITTED,
                    Submission.STATUS_FINAL,
                )
            ),
            distinct=True,
        ),
        **_count_by_choice(Submission.STATUS_CHOICES, "status"),
    )

    assignment_metrics = SubmissionExpertAssignment.objects.filter(
        submission__program=program
    ).aggregate(
        total=Count("id"),
        **_count_by_choice(SubmissionExpertAssignment.STATUS_CHOICES, "status"),
    )

    evaluation_metrics = Evaluation.objects.filter(submission__program=program).aggregate(
        total=Count("id"),
        **_count_by_choice(Evaluation.STATUS_CHOICES, "status"),
    )

    return {
        "program": {
            "id": program.pk,
            "name": program.name,
        },
        "registrations": {"total": registration_metrics["total"]},
        "participants": {
            "total": registration_metrics["participants_total"],
        },
        "applications": {
            "total": application_metrics["total"],
            "by_status": _choice_counts(
                application_metrics,
                "status",
                Application.STATUS_CHOICES,
            ),
            "by_participation_mode": _choice_counts(
                application_metrics,
                "participation_mode",
                Application.PARTICIPATION_MODE_CHOICES,
            ),
        },
        "teams": team_metrics,
        "submissions": {
            "total": submission_metrics["total"],
            "by_status": _choice_counts(
                submission_metrics,
                "status",
                Submission.STATUS_CHOICES,
            ),
            "applications_with_submitted_solution": submission_metrics[
                "applications_with_submitted_solution"
            ],
        },
        "expert_assignments": {
            "total": assignment_metrics["total"],
            "by_status": _choice_counts(
                assignment_metrics,
                "status",
                SubmissionExpertAssignment.STATUS_CHOICES,
            ),
        },
        "evaluations": {
            "total": evaluation_metrics["total"],
            "by_status": _choice_counts(
                evaluation_metrics,
                "status",
                Evaluation.STATUS_CHOICES,
            ),
        },
    }
