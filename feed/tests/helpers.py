from news.tests.helpers import create_project
from projects.models import Project
from vacancy.models import Vacancy


def create_vacancy(
    *,
    project: Project | None = None,
    role: str = "Feed vacancy",
    is_active: bool = True,
) -> Vacancy:
    return Vacancy.objects.create(
        project=project or create_project(name="Feed vacancy project"),
        role=role,
        description="Vacancy description",
        is_active=is_active,
    )
