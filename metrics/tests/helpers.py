from datetime import date
from uuid import uuid4

from projects.models import Project
from users.models import CustomUser
from vacancy.models import Vacancy


def unique_suffix() -> str:
    return uuid4().hex[:8]


def create_user(
    *,
    prefix: str = "metrics-user",
    is_staff: bool = False,
    is_superuser: bool = False,
    user_type: int = CustomUser.MEMBER,
) -> CustomUser:
    return CustomUser.objects.create_user(
        email=f"{prefix}-{unique_suffix()}@example.com",
        password="test_password_123",
        first_name="Иван",
        last_name="Иванов",
        birthday=date(2000, 1, 1),
        user_type=user_type,
        is_active=True,
        is_staff=is_staff or is_superuser,
        is_superuser=is_superuser,
    )


def create_project(*, leader: CustomUser | None = None) -> Project:
    return Project.objects.create(
        leader=leader or create_user(prefix="metrics-leader"),
        name=f"Metrics project {unique_suffix()}",
        description="Проект для метрик",
        draft=False,
    )


def create_vacancy(*, project: Project | None = None) -> Vacancy:
    return Vacancy.objects.create(
        project=project or create_project(),
        role=f"Metrics vacancy {unique_suffix()}",
        description="Вакансия для метрик",
    )
