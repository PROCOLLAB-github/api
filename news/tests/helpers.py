from datetime import timedelta
from uuid import uuid4

from django.utils import timezone

from files.models import UserFile
from industries.models import Industry
from news.models import News
from partner_programs.models import PartnerProgram
from projects.models import Project
from users.models import CustomUser


def unique_suffix() -> str:
    return uuid4().hex[:8]


def create_user(*, prefix: str = "news-test") -> CustomUser:
    suffix = unique_suffix()
    return CustomUser.objects.create_user(
        email=f"{prefix}-{suffix}@example.com",
        password="testpass123",
        first_name="Test",
        last_name="User",
        birthday="2000-01-01",
        is_active=True,
    )


def create_industry(*, name: str = "Industry") -> Industry:
    return Industry.objects.create(name=f"{name} {unique_suffix()}")


def create_project(
    *,
    leader: CustomUser | None = None,
    name: str = "Project",
    draft: bool = False,
    is_public: bool = True,
) -> Project:
    return Project.objects.create(
        leader=leader or create_user(prefix="news-project-leader"),
        name=f"{name} {unique_suffix()}",
        description="Project description",
        draft=draft,
        is_public=is_public,
        industry=create_industry(),
    )


def create_partner_program(
    *,
    manager: CustomUser | None = None,
    name: str = "Program",
) -> PartnerProgram:
    suffix = unique_suffix()
    now = timezone.now()
    program = PartnerProgram.objects.create(
        name=f"{name} {suffix}",
        tag=f"program-{suffix}",
        city="Moscow",
        datetime_registration_ends=now + timedelta(days=10),
        datetime_started=now - timedelta(days=1),
        datetime_finished=now + timedelta(days=30),
        draft=False,
    )
    if manager is not None:
        program.managers.add(manager)
    return program


def create_user_file(
    user: CustomUser,
    *,
    name: str = "attachment",
    extension: str = "pdf",
    mime_type: str = "application/pdf",
) -> UserFile:
    suffix = unique_suffix()
    return UserFile.objects.create(
        link=f"https://cdn.example.com/news/{suffix}/{name}.{extension}",
        user=user,
        name=name,
        extension=extension,
        mime_type=mime_type,
        size=1024,
    )


def create_news_for(obj, *, text: str = "News text", files=None, pin: bool = False) -> News:
    news = News.objects.add_news(obj, text=text, files=files or [])
    if pin:
        news.pin = True
        news.save(update_fields=["pin"])
    return news
