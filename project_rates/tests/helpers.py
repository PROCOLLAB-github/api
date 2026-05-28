from itertools import count

from django.utils import timezone

from partner_programs.models import PartnerProgram, PartnerProgramProject
from projects.models import Project
from project_rates.models import Criteria
from users.models import CustomUser

_counter = count(1)


def create_rate_user(
    *,
    prefix: str = "rate-user",
    user_type: int = CustomUser.MEMBER,
):
    index = next(_counter)
    return CustomUser.objects.create_user(
        email=f"{prefix}-{index}@example.com",
        password="pass",
        first_name="Rate",
        last_name="User",
        birthday="1990-01-01",
        user_type=user_type,
        is_active=True,
    )


def create_rate_expert(*, prefix: str = "rate-expert", program=None):
    user = create_rate_user(prefix=prefix, user_type=CustomUser.EXPERT)
    if program is not None:
        user.expert.programs.add(program)
    return user


def create_rate_program(**overrides):
    index = next(_counter)
    now = timezone.now()
    defaults = {
        "name": f"Rate Program {index}",
        "tag": f"rate-program-{index}",
        "description": "Program description",
        "city": "Moscow",
        "data_schema": {},
        "draft": False,
        "projects_availability": "all_users",
        "datetime_registration_ends": now + timezone.timedelta(days=10),
        "datetime_started": now - timezone.timedelta(days=1),
        "datetime_finished": now + timezone.timedelta(days=30),
        "max_project_rates": 2,
    }
    defaults.update(overrides)
    return PartnerProgram.objects.create(**defaults)


def create_rate_project(*, leader=None, name: str = "Rate Project", **overrides):
    index = next(_counter)
    defaults = {
        "leader": leader or create_rate_user(prefix="rate-leader"),
        "draft": False,
        "is_public": False,
        "name": f"{name} {index}",
    }
    defaults.update(overrides)
    return Project.objects.create(**defaults)


def link_project_to_program(program, project):
    return PartnerProgramProject.objects.create(
        partner_program=program,
        project=project,
    )


def create_rate_criteria(
    program,
    *,
    name: str = "Impact",
    type: str = "int",
    min_value=None,
    max_value=None,
):
    index = next(_counter)
    return Criteria.objects.create(
        name=f"{name} {index}",
        type=type,
        min_value=min_value,
        max_value=max_value,
        partner_program=program,
    )
