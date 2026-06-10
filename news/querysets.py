from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404

from news.models import News
from news.services import FEED_RECORD_TEXT
from partner_programs.models import PartnerProgram
from projects.models import Project

User = get_user_model()


def get_project_news_queryset(project_id: int) -> QuerySet[News]:
    project = get_object_or_404(Project, pk=project_id)
    return News.objects.get_news(obj=project).exclude(
        text=FEED_RECORD_TEXT,
        content_type__model="project",
    )


def get_user_news_queryset(user_id: int) -> QuerySet[News]:
    user = get_object_or_404(User, pk=user_id)
    return News.objects.get_news(obj=user)


def get_program_news_queryset(program_id: int) -> QuerySet[News]:
    program = get_object_or_404(PartnerProgram, pk=program_id)
    return News.objects.get_news(obj=program).order_by("-pin", "-datetime_created")


def get_news_queryset_for_context(kwargs: dict) -> QuerySet[News]:
    if kwargs.get("project_pk") is not None:
        return get_project_news_queryset(kwargs["project_pk"])
    if kwargs.get("partnerprogram_pk") is not None:
        return get_program_news_queryset(kwargs["partnerprogram_pk"])
    if kwargs.get("user_pk") is not None:
        return get_user_news_queryset(kwargs["user_pk"])
    return News.objects.none()
