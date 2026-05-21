from django.test import TestCase
from rest_framework.test import APIClient

from news.models import News

from .helpers import create_project_context


class ProjectScopedNewsRouteIntegrationTests(TestCase):
    def test_project_news_url_creates_news_record_for_project(self):
        client = APIClient()
        context = create_project_context(
            user_prefix="project-news-leader",
            draft=False,
            is_public=True,
        )
        client.force_authenticate(context.user)

        response = client.post(
            f"/projects/{context.project.id}/news/",
            {
                "text": "Project news text",
                "files": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        news = News.objects.get(pk=response.data["id"])
        self.assertEqual(news.content_object, context.project)
        self.assertEqual(news.text, "Project news text")
