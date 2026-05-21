from django.test import TestCase
from rest_framework.test import APIClient

from news.models import News

from .helpers import create_news_for, create_partner_program, create_user


class UserNewsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="user-news-owner")

    def test_user_can_create_own_news(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            f"/auth/users/{self.user.id}/news/",
            {"text": "User news"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        news = News.objects.get(pk=response.data["id"])
        self.assertEqual(news.content_object, self.user)
        self.assertEqual(news.text, "User news")

    def test_user_cannot_create_news_for_another_user(self):
        self.client.force_authenticate(create_user(prefix="user-news-outsider"))

        response = self.client.post(
            f"/auth/users/{self.user.id}/news/",
            {"text": "Forbidden user news"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(News.objects.get_news(self.user).exists())

    def test_user_news_list_returns_user_news(self):
        news = create_news_for(self.user, text="Visible user news")

        response = self.client.get(f"/auth/users/{self.user.id}/news/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["id"], news.id)

    def test_missing_user_context_returns_not_found(self):
        response = self.client.get("/auth/users/999999/news/")

        self.assertEqual(response.status_code, 404)


class PartnerProgramNewsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = create_user(prefix="program-news-manager")
        self.program = create_partner_program(manager=self.manager)

    def test_program_manager_can_create_program_news(self):
        self.client.force_authenticate(self.manager)

        response = self.client.post(
            f"/programs/{self.program.id}/news/",
            {"text": "Program news"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        news = News.objects.get(pk=response.data["id"])
        self.assertEqual(news.content_object, self.program)
        self.assertEqual(news.text, "Program news")

    def test_non_manager_cannot_create_program_news(self):
        self.client.force_authenticate(create_user(prefix="program-news-outsider"))

        response = self.client.post(
            f"/programs/{self.program.id}/news/",
            {"text": "Forbidden program news"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(News.objects.get_news(self.program).exists())

    def test_program_news_list_orders_pinned_news_first(self):
        regular_news = create_news_for(self.program, text="Regular program news")
        pinned_news = create_news_for(
            self.program,
            text="Pinned program news",
            pin=True,
        )

        response = self.client.get(f"/programs/{self.program.id}/news/")

        self.assertEqual(response.status_code, 200)
        news_ids = [item["id"] for item in response.data["results"]]
        self.assertEqual(news_ids, [pinned_news.id, regular_news.id])

    def test_missing_program_context_returns_not_found(self):
        response = self.client.get("/programs/999999/news/")

        self.assertEqual(response.status_code, 404)
