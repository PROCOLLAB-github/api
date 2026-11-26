"""Synthetic legacy program data with reproducible counts for each profile."""

from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import timezone

from partner_programs.models import (
    PartnerProgramFieldValue,
    PartnerProgramProject,
    PartnerProgramUserProfile,
    ProgramRegistration,
)
from partner_programs.tests.helpers import create_partner_program, create_program_field
from project_rates.models import ExpertCaseScope, ProjectExpertAssignment
from project_rates.tests.helpers import create_rate_expert
from projects.models import Collaborator, Project
from users.models import CustomUser, Member


@dataclass(frozen=True)
class Scale:
    participants: int
    projects: int
    experts: int


SCALES = {
    "small": Scale(1_000, 60, 12),
    "large": Scale(10_000, 500, 30),
    "pressure": Scale(25_000, 1_000, 48),
}
ENROLLMENT_SAMPLES = 12
CASE_NAMES = ("Городская среда", "Образование")
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FIELD_ID = "f" + "a" * 32
FIELD_LABEL = "Направление подготовки"
ARCHIVED_FIELD_LABEL = "Предыдущее название направления"
ANSWERS = ("Инженерия", "Математика")


def build_users(users):
    saved = CustomUser.objects.bulk_create(users, batch_size=500)
    Member.objects.bulk_create(
        [Member(user_id=user.pk) for user in saved], batch_size=500
    )
    return saved


def synthetic_user(email, **fields):
    return CustomUser(
        email=f"{email}@example.test",
        password="!",
        first_name="Тест",
        last_name="Участник",
        birthday=date(2000, 1, 1),
        user_type=CustomUser.MEMBER,
        is_active=True,
        **fields,
    )


class ProgramFixture:
    def __init__(self, scale):
        self.scale = scale
        self.now = timezone.now().replace(microsecond=0)
        self.manager = build_users([synthetic_user("perf-organizer")])[0]
        self.program = create_partner_program(
            tag="performance-fixture",
            is_competitive=True,
            is_distributed_evaluation=True,
            required_evaluators=2,
            max_project_rates=2,
            solution_storage_mode="legacy_project",
        )
        self.program.managers.add(self.manager)
        field = {
            "id": FIELD_ID,
            "label": FIELD_LABEL,
            "type": "select",
            "help_text": "",
            "required": True,
            "source": "own",
            "options": list(ANSWERS),
            "allow_other": False,
        }
        self.registration_schema = {"mode": "native", "fields": [field]}
        self.archived_schema = {
            "mode": "native",
            "fields": [{**field, "label": ARCHIVED_FIELD_LABEL}],
        }
        ProgramRegistration.objects.create(
            program=self.program,
            draft=self.registration_schema,
            published=self.registration_schema,
            published_version=1,
        )
        users = self.seed_participants()
        self.seed_projects(users)
        self.seed_experts()
        self.enrollees = build_users(
            [
                synthetic_user(f"perf-enrollee-{i:02d}")
                for i in range(ENROLLMENT_SAMPLES + 1)
            ]
        )

    def seed_participants(self):
        users = build_users(
            [
                synthetic_user(
                    f"perf-participant-{i:05d}",
                    city="Москва" if i % 4 < 2 else "Казань",
                    last_activity=(
                        self.now - timedelta(days=i % 28) if i % 4 != 3 else None
                    ),
                )
                for i in range(self.scale.participants)
            ]
        )
        self.registrations = PartnerProgramUserProfile.objects.bulk_create(
            [
                PartnerProgramUserProfile(
                    user=user,
                    partner_program=self.program,
                    partner_program_data={FIELD_ID: ANSWERS[i % 2]},
                    registration_schema=(
                        self.archived_schema if i == 0 else self.registration_schema
                    ),
                )
                for i, user in enumerate(users)
            ],
            batch_size=500,
        )
        self.answers_by_email = {
            user.email: (ARCHIVED_FIELD_LABEL if i == 0 else FIELD_LABEL, ANSWERS[i % 2])
            for i, user in enumerate(users)
        }
        return users

    def seed_projects(self, users):
        self.projects = Project.objects.bulk_create(
            [
                Project(
                    leader=users[i],
                    name=f"Тестовый проект {i:04d}",
                    description="Описание синтетического проекта",
                    region=users[i].city,
                    draft=False,
                    is_public=False,
                    cover=None,
                    cover_image_address=None,
                )
                for i in range(self.scale.projects)
            ],
            batch_size=500,
        )
        self.submitted_count = self.scale.projects * 4 // 5
        self.links = PartnerProgramProject.objects.bulk_create(
            [
                PartnerProgramProject(
                    partner_program=self.program,
                    project=project,
                    submitted=i < self.submitted_count,
                    datetime_submitted=self.now if i < self.submitted_count else None,
                )
                for i, project in enumerate(self.projects)
            ],
            batch_size=500,
        )
        Collaborator.objects.bulk_create(
            [
                Collaborator(
                    user=users[self.scale.projects * (j + 1) + i],
                    project=project,
                    role="Участник команды",
                )
                for i, project in enumerate(self.projects)
                for j in range(2)
            ],
            batch_size=500,
        )
        case_field = create_program_field(
            self.program,
            name="case",
            label="Кейс",
            field_type="select",
            is_required=True,
            show_filter=True,
            options=list(CASE_NAMES),
        )
        PartnerProgramFieldValue.objects.bulk_create(
            [
                PartnerProgramFieldValue(
                    program_project=link,
                    field=case_field,
                    value_text=CASE_NAMES[i % 2],
                )
                for i, link in enumerate(self.links)
            ],
            batch_size=500,
        )

    def seed_experts(self):
        experts = [
            create_rate_expert(prefix="perf-expert", program=self.program).expert
            for _ in range(self.scale.experts)
        ]
        pools = [experts[::2], experts[1::2]]
        self.case_pools = [
            {"case_name": name, "expert_ids": [expert.pk for expert in pool]}
            for name, pool in zip(CASE_NAMES, pools)
        ]
        ExpertCaseScope.objects.bulk_create(
            [
                ExpertCaseScope(
                    partner_program=self.program,
                    expert=expert,
                    all_cases=False,
                    case_names=[name],
                )
                for name, pool in zip(CASE_NAMES, pools)
                for expert in pool
            ]
        )
        self.existing_assignments = {
            (project.pk, pools[i % 2][i // 4 % len(pools[i % 2])].pk)
            for i, project in enumerate(self.projects[: self.submitted_count])
            if i % 4 < 2
        }
        ProjectExpertAssignment.objects.bulk_create(
            [
                ProjectExpertAssignment(
                    partner_program=self.program,
                    project_id=project_id,
                    expert_id=expert_id,
                )
                for project_id, expert_id in sorted(self.existing_assignments)
            ],
            batch_size=500,
        )

    def summary(self):
        return {
            "program_storage": self.program.solution_storage_mode,
            "participants": self.scale.participants,
            "participant_answers": len(self.answers_by_email),
            "projects": self.scale.projects,
            "submitted_projects": self.submitted_count,
            "project_collaborators": self.scale.projects * 2,
            "experts": self.scale.experts,
            "existing_assignments": len(self.existing_assignments),
            "required_evaluators": self.program.required_evaluators,
            "cases": len(CASE_NAMES),
        }
