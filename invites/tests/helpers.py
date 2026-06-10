from datetime import date, timedelta
from uuid import uuid4

from django.utils import timezone

from industries.models import Industry
from invites.models import Invite
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from projects.models import Collaborator, Project
from users.models import CustomUser


def unique_suffix() -> str:
    return uuid4().hex[:8]


def create_user(*, prefix: str = "invite-user", is_staff: bool = False) -> CustomUser:
    user = CustomUser.objects.create_user(
        email=f"{prefix}-{unique_suffix()}@example.com",
        password="very_strong_password",
        first_name="Иван",
        last_name="Иванов",
        birthday=date(2000, 1, 1),
    )
    user.is_active = True
    user.is_staff = is_staff
    user.save(update_fields=["is_active", "is_staff"])
    return user


def create_industry(*, name: str = "Industry") -> Industry:
    return Industry.objects.create(name=f"{name} {unique_suffix()}")


def create_project(
    *,
    leader: CustomUser | None = None,
    name: str = "Invite project",
    draft: bool = False,
    is_public: bool = True,
) -> Project:
    return Project.objects.create(
        leader=leader or create_user(prefix="project-leader"),
        name=f"{name} {unique_suffix()}",
        description="Проект для приглашений",
        industry=create_industry(),
        draft=draft,
        is_public=is_public,
    )


def invite_payload(project: Project, user: CustomUser, **overrides) -> dict:
    payload = {
        "project": project.id,
        "user": user.id,
        "motivational_letter": "Хотим пригласить вас в команду",
        "role": "Developer",
        "specialization": "Backend",
    }
    payload.update(overrides)
    return payload


def create_invite(
    *,
    project: Project | None = None,
    user: CustomUser | None = None,
    is_accepted: bool | None = None,
    role: str | None = "Developer",
    specialization: str | None = "Backend",
    motivational_letter: str | None = "Хотим пригласить вас в команду",
) -> Invite:
    return Invite.objects.create(
        project=project or create_project(),
        user=user or create_user(prefix="recipient"),
        is_accepted=is_accepted,
        role=role,
        specialization=specialization,
        motivational_letter=motivational_letter,
    )


def add_collaborator(
    *,
    project: Project,
    user: CustomUser,
    role: str = "Developer",
    specialization: str | None = "Backend",
) -> Collaborator:
    return Collaborator.objects.create(
        project=project,
        user=user,
        role=role,
        specialization=specialization,
    )


def create_program() -> PartnerProgram:
    now = timezone.now()
    return PartnerProgram.objects.create(
        name=f"Program {unique_suffix()}",
        tag=f"program-{unique_suffix()}",
        city="Moscow",
        datetime_registration_ends=now + timedelta(days=1),
        datetime_started=now,
        datetime_finished=now + timedelta(days=30),
    )


def link_project_to_program(
    *,
    project: Project,
    program: PartnerProgram | None = None,
) -> PartnerProgram:
    program = program or create_program()
    PartnerProgramProject.objects.create(partner_program=program, project=project)
    return program


def add_user_to_program(
    *,
    user: CustomUser,
    program: PartnerProgram,
) -> PartnerProgramUserProfile:
    return PartnerProgramUserProfile.objects.create(
        user=user,
        partner_program=program,
        partner_program_data={},
    )
