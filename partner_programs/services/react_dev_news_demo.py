# Roadmap: DEV-083.3
"""Повторяемый набор новостей для ручной проверки React-dev."""

from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet
from django.utils import timezone

from core.models import Like, View
from news.models import News, NewsComment
from projects.models import Project


DEMO_NEWS_PROJECT_NAME = "[DEMO] Новостная лента React-dev"
DEMO_NEWS_PROJECT_DESCRIPTION = (
    "Публичный демонстрационный проект для проверки новостной ленты React-dev."
)
DEMO_INTERNAL_PROGRAM_NEWS_TEXT = (
    "[DEMO][DEV-083] Внутренняя новость для участников программы"
)
DEMO_PROGRAM_NEWS_TEXTS = tuple(
    f"[DEMO][DEV-083] Новость программы {str(index).zfill(2)}: этап демонстрации"
    for index in range(1, 12)
)
DEMO_PROJECT_NEWS_TEXTS = tuple(
    f"[DEMO][DEV-083] Новость проекта {str(index).zfill(2)}: развитие решения"
    for index in range(1, 12)
)
DEMO_USER_NEWS_TEXTS = tuple(
    f"[DEMO][DEV-083] Новость пользователя {str(index).zfill(2)}: заметка участника"
    for index in range(1, 12)
)
DEMO_PAGINATED_COMMENT_TEXTS = tuple(
    f"[DEMO][DEV-083] Комментарий к новости {str(index).zfill(2)}"
    for index in range(1, 22)
)
DEMO_EXTRA_COMMENT_TEXTS = (
    "[DEMO][DEV-083] Комментарий к новости проекта",
    "[DEMO][DEV-083] Комментарий к новости пользователя",
)


class ReactDevNewsDemoDataError(Exception):
    """Набор новостей нельзя безопасно создать или обновить."""


@dataclass(frozen=True)
class ReactDevNewsDemoResult:
    project: Project
    program_news: tuple[News, ...]
    project_news: tuple[News, ...]
    user_news: tuple[News, ...]
    internal_news: News

    @property
    def all_news_ids(self) -> tuple[int, ...]:
        return tuple(
            news.pk
            for news in (
                *self.program_news,
                *self.project_news,
                *self.user_news,
                self.internal_news,
            )
        )

    @property
    def public_news_count(self) -> int:
        return len(self.program_news) + len(self.project_news) + len(self.user_news)


def _find_owned_project(*, expected_leader) -> Project | None:
    candidates = list(
        Project.objects.filter(name=DEMO_NEWS_PROJECT_NAME)
        .select_related("leader")
        .order_by("pk")
    )
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ReactDevNewsDemoDataError(
            "Точное имя DEMO-проекта новостной ленты соответствует нескольким "
            "проектам; требуется ручная проверка."
        )

    project = candidates[0]
    if expected_leader is None or project.leader_id != expected_leader.pk:
        raise ReactDevNewsDemoDataError(
            "Точное имя DEMO-проекта новостной ленты уже занято посторонним проектом."
        )
    return project


def _news_for_source(source, texts: tuple[str, ...]) -> QuerySet[News]:
    content_type = ContentType.objects.get_for_model(source)
    return News.objects.filter(
        content_type=content_type,
        object_id=source.pk,
        text__in=texts,
    )


def delete_react_dev_news_demo_data(*, program, users_by_key) -> None:
    """Удалить только записи с точными идентификаторами набора DEV-083."""

    expected_leader = users_by_key.get("participant1")
    project = _find_owned_project(expected_leader=expected_leader)

    # Тексты и ожидаемый источник вместе образуют идентификатор записи seed-набора:
    # общий префикс [DEMO] намеренно не используется для удаления.
    if program is not None:
        _news_for_source(
            program,
            (*DEMO_PROGRAM_NEWS_TEXTS, DEMO_INTERNAL_PROGRAM_NEWS_TEXT),
        ).delete()
    users = tuple(users_by_key.values())
    for index, text in enumerate(DEMO_USER_NEWS_TEXTS):
        user = users[index % len(users)]
        if user is not None:
            _news_for_source(user, (text,)).delete()
    if project is not None:
        _news_for_source(project, DEMO_PROJECT_NEWS_TEXTS).delete()
        project.delete()


def _ensure_project(*, leader) -> Project:
    project = _find_owned_project(expected_leader=leader)
    if project is None:
        return Project.objects.create(
            name=DEMO_NEWS_PROJECT_NAME,
            description=DEMO_NEWS_PROJECT_DESCRIPTION,
            leader=leader,
            draft=False,
            is_public=True,
        )

    project.description = DEMO_NEWS_PROJECT_DESCRIPTION
    project.draft = False
    project.is_public = True
    project.save(
        update_fields=(
            "description",
            "draft",
            "is_public",
            "datetime_updated",
        )
    )
    return project


def _ensure_news(*, source, text, audience, datetime_created) -> News:
    candidates = list(_news_for_source(source, (text,)).order_by("pk"))
    if len(candidates) > 1:
        raise ReactDevNewsDemoDataError(f"Найдены дубли точной DEMO-новости: {text}")

    if candidates:
        news = candidates[0]
        news.audience = audience
        news.pin = False
        news.save(update_fields=("audience", "pin", "datetime_updated"))
        news.files.clear()
    else:
        news = News.objects.add_news(
            source,
            text=text,
            files=[],
            audience=audience,
        )

    # Даты задаются явно, чтобы порядок страниц был стабильным и отличался у записей.
    News.objects.filter(pk=news.pk).update(
        datetime_created=datetime_created,
        datetime_updated=datetime_created,
    )
    news.datetime_created = datetime_created
    news.datetime_updated = datetime_created
    return news


def _ensure_news_group(*, source, texts, start_offset_hours) -> tuple[News, ...]:
    now = timezone.now()
    return tuple(
        _ensure_news(
            source=source,
            text=text,
            audience=News.Audience.PLATFORM,
            datetime_created=now - timezone.timedelta(hours=start_offset_hours + index),
        )
        for index, text in enumerate(texts)
    )


def _ensure_reactions_and_comments(*, result, users_by_key) -> None:
    users = tuple(users_by_key.values())
    news_content_type = ContentType.objects.get_for_model(News)
    targets = (
        (result.program_news[0], users[:2], users[:3]),
        (result.project_news[0], users[:1], users[:2]),
        (result.user_news[0], users[:3], users),
    )
    for news, like_users, view_users in targets:
        for user in like_users:
            Like.objects.get_or_create(
                user=user,
                content_type=news_content_type,
                object_id=news.pk,
            )
        for user in view_users:
            View.objects.get_or_create(
                user=user,
                content_type=news_content_type,
                object_id=news.pk,
            )

    comment_start = result.program_news[0].datetime_created
    for index, text in enumerate(DEMO_PAGINATED_COMMENT_TEXTS):
        comment, _created = NewsComment.objects.get_or_create(
            news=result.program_news[0],
            author=users[index % len(users)],
            text=text,
        )
        NewsComment.objects.filter(pk=comment.pk).update(
            datetime_created=comment_start + timezone.timedelta(minutes=index + 1),
            datetime_updated=None,
        )

    for news, text, author in (
        (result.project_news[0], DEMO_EXTRA_COMMENT_TEXTS[0], users[1]),
        (result.user_news[0], DEMO_EXTRA_COMMENT_TEXTS[1], users[2]),
    ):
        NewsComment.objects.get_or_create(news=news, author=author, text=text)


def ensure_react_dev_news_demo_data(*, program, users_by_key) -> ReactDevNewsDemoResult:
    """Создать или обновить точный набор DEV-083 без дублирования записей."""

    project = _ensure_project(leader=users_by_key["participant1"])
    program_news = _ensure_news_group(
        source=program,
        texts=DEMO_PROGRAM_NEWS_TEXTS,
        start_offset_hours=1,
    )
    project_news = _ensure_news_group(
        source=project,
        texts=DEMO_PROJECT_NEWS_TEXTS,
        start_offset_hours=20,
    )

    users = tuple(users_by_key.values())
    user_news = tuple(
        _ensure_news(
            source=users[index % len(users)],
            text=text,
            audience=News.Audience.PLATFORM,
            datetime_created=timezone.now() - timezone.timedelta(hours=40 + index),
        )
        for index, text in enumerate(DEMO_USER_NEWS_TEXTS)
    )
    internal_news = _ensure_news(
        source=program,
        text=DEMO_INTERNAL_PROGRAM_NEWS_TEXT,
        audience=News.Audience.PROGRAM_PARTICIPANTS,
        datetime_created=timezone.now() - timezone.timedelta(minutes=30),
    )

    result = ReactDevNewsDemoResult(
        project=project,
        program_news=program_news,
        project_news=project_news,
        user_news=user_news,
        internal_news=internal_news,
    )
    _ensure_reactions_and_comments(result=result, users_by_key=users_by_key)
    return result
