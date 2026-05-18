from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from django.utils import timezone

from industries.models import Industry
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from projects.models import (
    Collaborator,
    Company,
    Project,
    ProjectCompany,
    ProjectGoal,
    Resource,
)
from users.models import CustomUser
from vacancy.models import Vacancy


@dataclass(frozen=True)
class ProjectTestContext:
    user: CustomUser
    project: Project


def unique_suffix() -> str:
    return uuid4().hex[:8]


def unique_digits(length: int = 10) -> str:
    return str(uuid4().int)[:length]


def create_user(*, prefix: str = "projects-test") -> CustomUser:
    suffix = unique_suffix()
    return CustomUser.objects.create_user(
        email=f"{prefix}-{suffix}@example.com",
        password="testpass123",
        first_name="Test",
        last_name="User",
        birthday="2000-01-01",
        is_active=True,
    )


def create_staff_user(*, prefix: str = "projects-admin") -> CustomUser:
    suffix = unique_suffix()
    return CustomUser.objects.create_superuser(
        email=f"{prefix}-{suffix}@example.com",
        password="testpass123",
        first_name="Admin",
        last_name="User",
    )


def create_industry(*, name: str = "Industry") -> Industry:
    return Industry.objects.create(name=f"{name} {unique_suffix()}")


def create_project(
    *,
    leader: CustomUser | None = None,
    name: str = "Project",
    description: str = "Project description",
    draft: bool = True,
    is_public: bool = True,
    industry: Industry | None = None,
) -> Project:
    return Project.objects.create(
        leader=leader or create_user(prefix="project-leader"),
        name=f"{name} {unique_suffix()}",
        description=description,
        draft=draft,
        is_public=is_public,
        industry=industry or create_industry(),
    )


def create_project_context(
    *,
    user_prefix: str = "projects-test",
    project_name: str = "Project",
    draft: bool = True,
    is_public: bool = True,
) -> ProjectTestContext:
    user = create_user(prefix=user_prefix)
    project = create_project(
        leader=user,
        name=project_name,
        draft=draft,
        is_public=is_public,
    )
    return ProjectTestContext(user=user, project=project)


def create_collaborator(
    project: Project,
    *,
    user: CustomUser | None = None,
    role: str = "Участник",
    specialization: str | None = None,
) -> Collaborator:
    collaborator, _ = Collaborator.objects.get_or_create(
        project=project,
        user=user or create_user(prefix="project-collaborator"),
        defaults={
            "role": role,
            "specialization": specialization,
        },
    )
    return collaborator


def create_partner_program(
    *,
    name: str = "Program",
    is_competitive: bool = False,
    finished: bool = False,
    submission_closed: bool = False,
) -> PartnerProgram:
    suffix = unique_suffix()
    now = timezone.now()
    datetime_finished = now - timedelta(days=1) if finished else now + timedelta(days=30)
    registration_ends = (
        now - timedelta(days=1) if submission_closed else now + timedelta(days=10)
    )
    return PartnerProgram.objects.create(
        name=f"{name} {suffix}",
        tag=f"program-{suffix}",
        city="Moscow",
        is_competitive=is_competitive,
        datetime_registration_ends=registration_ends,
        datetime_started=now - timedelta(days=1),
        datetime_finished=datetime_finished,
        draft=False,
    )


def add_program_member(
    program: PartnerProgram,
    user: CustomUser,
    *,
    project: Project | None = None,
) -> PartnerProgramUserProfile:
    return PartnerProgramUserProfile.objects.create(
        user=user,
        partner_program=program,
        project=project,
        partner_program_data={},
    )


def link_project_to_program(
    project: Project,
    program: PartnerProgram,
    *,
    submitted: bool = False,
) -> PartnerProgramProject:
    return PartnerProgramProject.objects.create(
        project=project,
        partner_program=program,
        submitted=submitted,
    )


def create_company(*, name: str = "Company", inn: str | None = None) -> Company:
    suffix = unique_suffix()
    return Company.objects.create(
        name=f"{name} {suffix}",
        inn=inn or unique_digits(10),
    )


def create_project_company(
    project: Project,
    company: Company | None = None,
    *,
    contribution: str = "Contribution",
    decision_maker: CustomUser | None = None,
) -> ProjectCompany:
    return ProjectCompany.objects.create(
        project=project,
        company=company or create_company(),
        contribution=contribution,
        decision_maker=decision_maker,
    )


def create_resource(
    project: Project,
    *,
    type: str = Resource.ResourceType.INFORMATION,
    description: str = "Resource description",
    partner_company: Company | None = None,
) -> Resource:
    if partner_company:
        ProjectCompany.objects.get_or_create(
            project=project,
            company=partner_company,
        )

    resource = Resource(
        project=project,
        type=type,
        description=description,
        partner_company=partner_company,
    )
    resource.full_clean()
    resource.save()
    return resource


def create_project_goal(
    project: Project,
    *,
    responsible: CustomUser | None = None,
    title: str = "Project goal",
    is_done: bool = False,
) -> ProjectGoal:
    return ProjectGoal.objects.create(
        project=project,
        title=f"{title} {unique_suffix()}",
        responsible=responsible or project.leader,
        is_done=is_done,
    )


def create_vacancy(
    project: Project,
    *,
    role: str = "Backend developer",
    is_active: bool = True,
) -> Vacancy:
    return Vacancy.objects.create(
        project=project,
        role=f"{role} {unique_suffix()}",
        description="Vacancy description",
        is_active=is_active,
    )
