from typing import Any

from news.models import News
from partner_programs.models import PartnerProgram
from projects.models import Project
from users.models import CustomUser


FEED_RECORD_TEXT = ""


def is_feed_record(news: News) -> bool:
    return news.text == FEED_RECORD_TEXT


def is_content_news(news: News) -> bool:
    return not is_feed_record(news)


def create_project_news(
    project: Project,
    author,
    data: dict[str, Any],
) -> News:
    return News.objects.add_news(project, **data)


def create_user_news(
    user: CustomUser,
    author,
    data: dict[str, Any],
) -> News:
    return News.objects.add_news(user, **data)


def create_program_news(
    program: PartnerProgram,
    author,
    data: dict[str, Any],
) -> News:
    return News.objects.add_news(program, **data)
