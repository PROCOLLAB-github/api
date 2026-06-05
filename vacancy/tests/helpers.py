from datetime import date, timedelta
from uuid import uuid4

from django.utils import timezone

from core.models import Skill, SkillCategory
from files.models import UserFile
from projects.models import Project
from users.models import CustomUser
from vacancy.constants import WorkExperience, WorkFormat, WorkSchedule
from vacancy.models import Vacancy, VacancyResponse


def create_user(
    *,
    prefix: str = "vacancy-user",
    is_active: bool = True,
) -> CustomUser:
    user = CustomUser.objects.create_user(
        email=f"{prefix}-{uuid4().hex}@example.com",
        password="very_strong_password",
        first_name="Иван",
        last_name="Иванов",
        birthday=date(2000, 1, 1),
    )
    user.is_active = is_active
    user.save(update_fields=["is_active"])
    return user


def create_project(
    *,
    leader: CustomUser | None = None,
    name: str = "Проект с вакансией",
    draft: bool = False,
    is_public: bool = True,
) -> Project:
    return Project.objects.create(
        leader=leader or create_user(prefix="vacancy-leader"),
        name=name,
        description="Описание проекта",
        draft=draft,
        is_public=is_public,
    )


def create_skill(*, name: str = "Python") -> Skill:
    category, _ = SkillCategory.objects.get_or_create(name="Backend")
    return Skill.objects.create(name=f"{name}-{uuid4().hex}", category=category)


def create_user_file(
    *,
    user: CustomUser,
    link: str | None = None,
) -> UserFile:
    return UserFile.objects.create(
        user=user,
        link=link or f"https://cdn.example.com/{uuid4().hex}.pdf",
        name="cv",
        extension="pdf",
        mime_type="application/pdf",
        size=1024,
    )


def vacancy_payload(project: Project, skills: list[Skill] | None = None, **overrides):
    skills = skills if skills is not None else [create_skill()]
    payload = {
        "role": "Backend developer",
        "specialization": "Backend",
        "required_skills_ids": [skill.id for skill in skills],
        "description": "Нужен Python-разработчик",
        "project": project.id,
        "required_experience": WorkExperience.NO_EXPERIENCE.value,
        "work_schedule": WorkSchedule.FULL_TIME.value,
        "work_format": WorkFormat.REMOTE.value,
        "salary": 100000,
    }
    payload.update(overrides)
    return payload


def create_vacancy(
    *,
    project: Project | None = None,
    role: str = "Backend developer",
    is_active: bool = True,
    datetime_created=None,
    required_experience: str | None = WorkExperience.NO_EXPERIENCE.name.lower(),
    work_schedule: str | None = WorkSchedule.FULL_TIME.name.lower(),
    work_format: str | None = WorkFormat.REMOTE.name.lower(),
    salary: int | None = 100000,
) -> Vacancy:
    vacancy = Vacancy.objects.create(
        project=project or create_project(),
        role=role,
        specialization="Backend",
        description="Описание вакансии",
        is_active=is_active,
        required_experience=required_experience,
        work_schedule=work_schedule,
        work_format=work_format,
        salary=salary,
    )
    if datetime_created is not None:
        Vacancy.objects.filter(pk=vacancy.pk).update(datetime_created=datetime_created)
        vacancy.refresh_from_db()
    return vacancy


def create_old_vacancy(*, days: int = 31, **kwargs) -> Vacancy:
    return create_vacancy(
        datetime_created=timezone.now() - timedelta(days=days),
        **kwargs,
    )


def create_vacancy_response(
    *,
    user: CustomUser | None = None,
    vacancy: Vacancy | None = None,
    is_approved: bool | None = None,
    why_me: str = "Подхожу по опыту",
    accompanying_file: UserFile | None = None,
) -> VacancyResponse:
    return VacancyResponse.objects.create(
        user=user or create_user(prefix="vacancy-response-user"),
        vacancy=vacancy or create_vacancy(),
        is_approved=is_approved,
        why_me=why_me,
        accompanying_file=accompanying_file,
    )
