from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Exists, OuterRef, Q, QuerySet, Value
from django.db.models.functions import Concat
from django.http import Http404
from django.shortcuts import get_object_or_404

from core.models import Like
from news.access import can_view_news_in_react_feed
from news.models import News
from partner_programs.models import PartnerProgram
from projects.models import Project
from users.models import CustomUser


NEWS_SOURCE_PROGRAM = "program"
NEWS_SOURCE_PROJECT = "project"
NEWS_SOURCE_USER = "user"
NEWS_SOURCES = (
    NEWS_SOURCE_PROGRAM,
    NEWS_SOURCE_PROJECT,
    NEWS_SOURCE_USER,
)


def _with_feed_annotations(queryset: QuerySet[News], user) -> QuerySet[News]:
    news_content_type = ContentType.objects.get_for_model(News)
    user_like = Like.objects.filter(
        content_type=news_content_type,
        object_id=OuterRef("pk"),
        user=user,
    )
    return queryset.annotate(
        likes_count=Count("likes", distinct=True),
        comments_count=Count("comments", distinct=True),
        views_count=Count("views", distinct=True),
        is_user_liked=Exists(user_like),
    )


def _content_source(source: str):
    mapping = {
        NEWS_SOURCE_PROGRAM: PartnerProgram,
        NEWS_SOURCE_PROJECT: Project,
        NEWS_SOURCE_USER: CustomUser,
    }
    return mapping[source]


def get_react_news_feed_queryset(
    *,
    source: str,
    search: str,
    user,
) -> QuerySet[News]:
    """Строит вкладку только из публикаций выбранного доменного источника."""
    source_model = _content_source(source)
    source_content_type = ContentType.objects.get_for_model(source_model)
    source_objects = source_model.objects.all()

    if source == NEWS_SOURCE_PROJECT:
        source_objects = source_objects.filter(draft=False, is_public=True)

    if search:
        if source in (NEWS_SOURCE_PROGRAM, NEWS_SOURCE_PROJECT):
            matching_source_ids = source_objects.filter(
                name__icontains=search
            ).values_list("id", flat=True)
        else:
            matching_source_ids = (
                source_objects.annotate(
                    search_full_name=Concat(
                        "first_name",
                        Value(" "),
                        "last_name",
                    ),
                    search_reverse_full_name=Concat(
                        "last_name",
                        Value(" "),
                        "first_name",
                    ),
                )
                .filter(
                    Q(first_name__icontains=search)
                    | Q(last_name__icontains=search)
                    | Q(search_full_name__icontains=search)
                    | Q(search_reverse_full_name__icontains=search)
                )
                .values_list("id", flat=True)
            )
        search_filter = Q(text__icontains=search) | Q(object_id__in=matching_source_ids)
    else:
        search_filter = Q()

    queryset = (
        News.objects.filter(
            content_type=source_content_type,
            object_id__in=source_objects.values_list("id", flat=True),
            audience=News.Audience.PLATFORM,
        )
        .exclude(text__regex=r"^\s*$")
        .filter(search_filter)
        .select_related("content_type")
        .prefetch_related("content_object", "files")
        .order_by("-datetime_created", "-id")
    )
    return _with_feed_annotations(queryset, user)


def get_react_feed_news_or_404(*, news_id: int, user) -> News:
    queryset = _with_feed_annotations(
        News.objects.select_related("content_type").prefetch_related(
            "content_object", "files"
        ),
        user,
    )
    news = get_object_or_404(queryset, pk=news_id)
    if not can_view_news_in_react_feed(user, news):
        # Единый 404 не раскрывает существование внутренней публикации.
        raise Http404
    return news
