from django.test import TestCase
from rest_framework.test import APIClient

from .helpers import create_news_for, create_project, create_user


class NewsFeedTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="news-feed-user")
        self.client.force_authenticate(self.user)

    def test_feed_returns_user_news_when_news_filter_requested(self):
        news = create_news_for(self.user, text="User feed news")

        response = self.client.get("/feed/?type=news")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(item["type_model"], "news")
        self.assertEqual(item["content"]["id"], news.id)
        self.assertEqual(item["content"]["text"], "User feed news")

    def test_feed_returns_project_news_as_news_content(self):
        project = create_project(name="Feed project")
        news = create_news_for(project, text="Project feed news")

        response = self.client.get("/feed/?type=project")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(item["type_model"], "news")
        self.assertEqual(item["content"]["id"], news.id)
        self.assertEqual(item["content"]["text"], "Project feed news")

    def test_feed_excludes_news_for_private_project(self):
        private_project = create_project(name="Private project", is_public=False)
        create_news_for(private_project, text="Private project news")

        response = self.client.get("/feed/?type=project")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])
