from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Like, View
from news.models import News
from projects.models import ProjectNews

from .helpers import create_project, create_project_context, create_user


class ProjectNewsRegressionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        context = create_project_context(
            user_prefix="project-news-leader",
            draft=False,
            is_public=True,
        )
        self.leader = context.user
        self.project = context.project
        self.client.force_authenticate(self.leader)

    def _content_type(self):
        return ContentType.objects.get_for_model(News)

    def test_leader_can_create_project_news(self):
        response = self.client.post(
            f"/projects/{self.project.id}/news/",
            {
                "text": "Project news text",
                "files": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        news = News.objects.get(pk=response.data["id"])
        self.assertEqual(news.content_object, self.project)
        self.assertEqual(news.text, "Project news text")
        self.assertFalse(ProjectNews.objects.exists())

    def test_project_news_list_returns_only_visible_news_for_current_project(self):
        visible_news = News.objects.add_news(self.project, text="Visible project news")
        News.objects.add_news(self.project, text="")
        other_project = create_project(draft=False, is_public=True)
        other_news = News.objects.add_news(other_project, text="Other project news")

        response = self.client.get(f"/projects/{self.project.id}/news/")

        self.assertEqual(response.status_code, 200)
        news_ids = {item["id"] for item in response.data["results"]}
        self.assertIn(visible_news.id, news_ids)
        self.assertNotIn(other_news.id, news_ids)

    def test_project_news_detail_is_available_for_modal_view(self):
        news = News.objects.add_news(self.project, text="Modal project news")

        response = self.client.get(f"/projects/{self.project.id}/news/{news.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], news.id)
        self.assertEqual(response.data["text"], "Modal project news")

    def test_project_news_can_be_marked_viewed_and_liked(self):
        news = News.objects.add_news(self.project, text="Interactive project news")
        content_type = self._content_type()

        viewed_response = self.client.post(
            f"/projects/{self.project.id}/news/{news.id}/set_viewed/",
            {"is_viewed": True},
            format="json",
        )
        liked_response = self.client.post(
            f"/projects/{self.project.id}/news/{news.id}/set_liked/",
            {"is_liked": True},
            format="json",
        )

        self.assertEqual(viewed_response.status_code, 200)
        self.assertEqual(liked_response.status_code, 200)
        self.assertTrue(
            View.objects.filter(
                content_type=content_type,
                object_id=news.id,
                user=self.leader,
            ).exists()
        )
        self.assertTrue(
            Like.objects.filter(
                content_type=content_type,
                object_id=news.id,
                user=self.leader,
            ).exists()
        )

        unliked_response = self.client.post(
            f"/projects/{self.project.id}/news/{news.id}/set_liked/",
            {"is_liked": False},
            format="json",
        )

        self.assertEqual(unliked_response.status_code, 200)
        self.assertFalse(
            Like.objects.filter(
                content_type=content_type,
                object_id=news.id,
                user=self.leader,
            ).exists()
        )

    def test_project_leader_can_edit_and_delete_project_news(self):
        news = News.objects.add_news(self.project, text="Initial project news")

        patch_response = self.client.patch(
            f"/projects/{self.project.id}/news/{news.id}/",
            {
                "text": "Updated project news",
                "files": [],
            },
            format="json",
        )

        self.assertEqual(patch_response.status_code, 200)
        news.refresh_from_db()
        self.assertEqual(news.text, "Updated project news")

        delete_response = self.client.delete(
            f"/projects/{self.project.id}/news/{news.id}/"
        )

        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(News.objects.filter(pk=news.id).exists())

    def test_non_leader_cannot_create_project_news(self):
        non_leader = create_user(prefix="project-news-non-leader")
        self.client.force_authenticate(non_leader)

        response = self.client.post(
            f"/projects/{self.project.id}/news/",
            {
                "text": "Forbidden project news",
                "files": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            News.objects.get_news(self.project)
            .filter(text="Forbidden project news")
            .exists()
        )
