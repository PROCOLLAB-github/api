from django.contrib.auth.models import AnonymousUser

from news.models import News
from news.services import is_content_news
from partner_programs.models import PartnerProgram
from projects.models import Project
from users.models import CustomUser


def is_administrative_user(user: CustomUser | AnonymousUser | None) -> bool:
    """Проверяет административный доступ без привязки к конкретной программе."""
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def can_view_program_participant_news(user, program: PartnerProgram) -> bool:
    """Разрешает внутренние новости участникам, менеджерам и администраторам."""
    if not user or not user.is_authenticated:
        return False
    if is_administrative_user(user) or program.is_manager(user):
        return True
    return program.users.filter(pk=user.pk).exists()


def can_view_news_in_react_feed(user, news: News) -> bool:
    """Проверяет доступ к полноценной публикации нового React-контура."""
    if not user or not user.is_authenticated or not is_content_news(news):
        return False

    source = news.content_object
    if isinstance(source, PartnerProgram):
        if news.audience == News.Audience.PLATFORM:
            return True
        return can_view_program_participant_news(user, source)

    if isinstance(source, Project):
        return not source.draft and source.is_public

    return isinstance(source, CustomUser)
