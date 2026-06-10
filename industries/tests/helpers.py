from datetime import date
from uuid import uuid4

from industries.models import Industry
from projects.models import Project
from users.models import CustomUser


def unique_suffix() -> str:
    return uuid4().hex[:8]


def create_user(*, prefix: str = "industry-user", is_staff: bool = False):
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


def create_project_with_industry(
    *,
    industry: Industry,
    leader: CustomUser | None = None,
) -> Project:
    return Project.objects.create(
        leader=leader or create_user(prefix="project-leader"),
        name=f"Project {unique_suffix()}",
        description="Проект с отраслью",
        industry=industry,
        draft=False,
        is_public=True,
    )
