from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Like, View
from news.models import News

from .helpers import create_news_for, create_project, create_user


class ProjectScopedNewsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.leader = create_user(prefix="project-news-leader")
        self.project = create_project(leader=self.leader)

    def test_project_leader_can_create_project_news(self):
        self.client.force_authenticate(self.leader)

        response = self.client.post(
            f"/projects/{self.project.id}/news/",
            {"text": "Project news"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        news = News.objects.get(pk=response.data["id"])
        self.assertEqual(news.content_object, self.project)
        self.assertEqual(news.text, "Project news")

    def test_non_leader_cannot_create_project_news(self):
        self.client.force_authenticate(create_user(prefix="project-news-outsider"))

        response = self.client.post(
            f"/projects/{self.project.id}/news/",
            {"text": "Forbidden news"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            News.objects.get_news(self.project).filter(text="Forbidden news").exists()
        )

    def test_project_news_list_excludes_feed_records_without_text(self):
        visible_news = create_news_for(self.project, text="Visible project news")
        create_news_for(self.project, text="")

        response = self.client.get(f"/projects/{self.project.id}/news/")

        self.assertEqual(response.status_code, 200)
        news_ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(news_ids, {visible_news.id})

    def test_missing_project_context_returns_not_found(self):
        response = self.client.get("/projects/999999/news/")

        self.assertEqual(response.status_code, 404)

    def test_project_news_detail_can_be_updated_and_deleted_by_leader(self):
        self.client.force_authenticate(self.leader)
        news = create_news_for(self.project, text="Initial text")

        update_response = self.client.patch(
            f"/projects/{self.project.id}/news/{news.id}/",
            {"text": "Updated text"},
            format="json",
        )

        self.assertEqual(update_response.status_code, 200)
        news.refresh_from_db()
        self.assertEqual(news.text, "Updated text")

        delete_response = self.client.delete(
            f"/projects/{self.project.id}/news/{news.id}/"
        )

        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(News.objects.filter(pk=news.id).exists())

    def test_project_news_can_be_marked_viewed_and_liked(self):
        user = create_user(prefix="project-news-reader")
        self.client.force_authenticate(user)
        news = create_news_for(self.project, text="Interactive news")
        news_content_type = ContentType.objects.get_for_model(News)

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
        self.assertTrue(
            View.objects.filter(
                user=user,
                content_type=news_content_type,
                object_id=news.id,
            ).exists()
        )
        self.assertEqual(liked_response.status_code, 200)
        self.assertTrue(
            Like.objects.filter(
                user=user,
                content_type=news_content_type,
                object_id=news.id,
            ).exists()
        )

        unlike_response = self.client.post(
            f"/projects/{self.project.id}/news/{news.id}/set_liked/",
            {"is_liked": False},
            format="json",
        )

        self.assertEqual(unlike_response.status_code, 200)
        self.assertFalse(
            Like.objects.filter(
                user=user,
                content_type=news_content_type,
                object_id=news.id,
            ).exists()
        )
