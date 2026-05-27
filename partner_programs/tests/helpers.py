from itertools import count

from django.contrib.auth import get_user_model
from django.utils import timezone

from courses.models import Course, CourseAccessType, CourseContentStatus
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from projects.models import Project

User = get_user_model()

_counter = count(1)


def create_user(*, prefix: str = "program-user", **overrides):
    index = next(_counter)
    defaults = {
        "email": f"{prefix}-{index}@example.com",
        "password": "pass",
        "first_name": "Program",
        "last_name": "User",
        "birthday": "1990-01-01",
    }
    defaults.update(overrides)
    return User.objects.create_user(**defaults)


def create_partner_program(**overrides) -> PartnerProgram:
    index = next(_counter)
    now = timezone.now()
    defaults = {
        "name": f"Program {index}",
        "tag": f"program-{index}",
        "description": "Program description",
        "city": "Moscow",
        "data_schema": {},
        "draft": False,
        "projects_availability": "all_users",
        "datetime_registration_ends": now + timezone.timedelta(days=30),
        "datetime_started": now - timezone.timedelta(days=1),
        "datetime_finished": now + timezone.timedelta(days=60),
    }
    defaults.update(overrides)
    return PartnerProgram.objects.create(**defaults)


def create_program_field(
    program: PartnerProgram,
    *,
    field_type: str = "text",
    name: str | None = None,
    label: str | None = None,
    is_required: bool = False,
    options: list[str] | None = None,
    show_filter: bool = False,
) -> PartnerProgramField:
    index = next(_counter)
    return PartnerProgramField.objects.create(
        partner_program=program,
        name=name or f"field_{index}",
        label=label or f"Field {index}",
        field_type=field_type,
        is_required=is_required,
        options="|".join(options) if options else "",
        show_filter=show_filter,
    )


def create_project(*, leader=None, **overrides) -> Project:
    index = next(_counter)
    defaults = {
        "leader": leader or create_user(prefix="project-leader"),
        "name": f"Project {index}",
        "description": "Project description",
        "draft": False,
        "is_public": False,
    }
    defaults.update(overrides)
    return Project.objects.create(**defaults)


def create_program_member(
    program: PartnerProgram,
    *,
    user=None,
    project: Project | None = None,
    data: dict | None = None,
) -> PartnerProgramUserProfile:
    return PartnerProgramUserProfile.objects.create(
        user=user or create_user(prefix="program-member"),
        partner_program=program,
        project=project,
        partner_program_data=data or {},
    )


def create_program_project(
    program: PartnerProgram,
    *,
    project: Project | None = None,
    submitted: bool = False,
) -> PartnerProgramProject:
    return PartnerProgramProject.objects.create(
        partner_program=program,
        project=project or create_project(),
        submitted=submitted,
        datetime_submitted=timezone.now() if submitted else None,
    )


def create_course(program: PartnerProgram, **overrides) -> Course:
    defaults = {
        "title": "Program course",
        "partner_program": program,
        "access_type": CourseAccessType.ALL_USERS,
        "status": CourseContentStatus.PUBLISHED,
    }
    defaults.update(overrides)
    return Course.objects.create(**defaults)


def project_apply_payload(
    *,
    project: dict | None = None,
    program_field_values: list[dict] | None = None,
) -> dict:
    project_data = {
        "name": "Submitted project",
        "description": "Submitted project description",
    }
    if project:
        project_data.update(project)
    return {
        "project": project_data,
        "program_field_values": program_field_values or [],
    }
