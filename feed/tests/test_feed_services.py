from django.test import TestCase

from core.services import set_like
from feed.services import create_news_for_model, delete_news_for_model, get_liked_news
from news.models import News
from news.services import FEED_RECORD_TEXT
from news.tests.helpers import create_news_for, create_project, create_user


class FeedServiceTests(TestCase):
    def test_get_liked_news_returns_ids_liked_by_user(self):
        user = create_user(prefix="feed-liked-user")
        project = create_project(name="Liked feed project")
        liked_news = create_news_for(project, text="Liked feed news")
        other_news = create_news_for(project, text="Other feed news")
        set_like(liked_news, user, True)

        liked_ids = get_liked_news(user, [liked_news, other_news])

        self.assertEqual(list(liked_ids), [liked_news.id])

    def test_create_news_for_model_creates_single_feed_record(self):
        project = create_project(name="Feed record project")

        create_news_for_model(project)
        create_news_for_model(project)

        self.assertEqual(
            News.objects.get_news(project).filter(text=FEED_RECORD_TEXT).count(),
            1,
        )

    def test_delete_news_for_model_deletes_only_feed_record(self):
        project = create_project(name="Delete feed record project")
        content_news = create_news_for(project, text="Content news")
        create_news_for_model(project)

        delete_news_for_model(project)

        self.assertFalse(
            News.objects.get_news(project).filter(text=FEED_RECORD_TEXT).exists()
        )
        self.assertTrue(News.objects.filter(pk=content_news.id).exists())
