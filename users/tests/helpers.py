from datetime import date, timedelta

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from core.models import Skill, SkillCategory, SkillToObject, Specialization, SpecializationCategory
from files.models import UserFile
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from projects.models import Project
from users.models import CustomUser


def build_user(
    email: str = "user@example.com",
    *,
    password: str = "very_strong_password",
    first_name: str = "Иван",
    last_name: str = "Иванов",
    user_type: int = CustomUser.MEMBER,
    is_active: bool = True,
    **extra_fields,
) -> CustomUser:
    defaults = {
        "email": email,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
        "birthday": date(2000, 1, 1),
        "user_type": user_type,
        "is_active": is_active,
    }
    defaults.update(extra_fields)
    return CustomUser.objects.create_user(**defaults)


def build_superuser(email: str = "admin@example.com") -> CustomUser:
    return CustomUser.objects.create_superuser(
        email=email,
        password="very_strong_password",
        first_name="Админ",
        last_name="Админов",
    )


def build_skill(name: str = "Python") -> Skill:
    category, _ = SkillCategory.objects.get_or_create(name="Backend")
    return Skill.objects.create(name=name, category=category)


def attach_skill(user: CustomUser, skill: Skill) -> SkillToObject:
    return SkillToObject.objects.create(
        skill=skill,
        content_type=ContentType.objects.get_for_model(CustomUser),
        object_id=user.id,
    )


def build_specialization(name: str = "Backend developer") -> Specialization:
    category, _ = SpecializationCategory.objects.get_or_create(name="IT")
    return Specialization.objects.create(name=name, category=category)


def build_user_file(
    user: CustomUser,
    *,
    link: str = "https://cdn.example.com/file.pdf",
    extension: str = "pdf",
    size: int = 1024,
) -> UserFile:
    return UserFile.objects.create(
        user=user,
        link=link,
        name="file",
        extension=extension,
        mime_type="application/pdf",
        size=size,
    )


def build_project(
    leader: CustomUser,
    *,
    name: str = "Проект",
    draft: bool = False,
) -> Project:
    return Project.objects.create(name=name, leader=leader, draft=draft)


def build_partner_program(
    *,
    name: str = "Программа",
    tag: str = "program",
    draft: bool = False,
) -> PartnerProgram:
    now = timezone.now()
    return PartnerProgram.objects.create(
        name=name,
        tag=tag,
        city="Екатеринбург",
        draft=draft,
        datetime_started=now - timedelta(days=1),
        datetime_registration_ends=now + timedelta(days=10),
        datetime_finished=now + timedelta(days=20),
    )


def add_user_to_program(
    user: CustomUser,
    program: PartnerProgram,
    *,
    project: Project | None = None,
) -> PartnerProgramUserProfile:
    return PartnerProgramUserProfile.objects.create(
        user=user,
        project=project,
        partner_program=program,
        partner_program_data={},
    )
