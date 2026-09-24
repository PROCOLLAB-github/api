from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from core.services import set_like
from feed.services import create_news_for_model
from feed.tests.helpers import create_vacancy
from news.models import News
from news.services import FEED_RECORD_TEXT
from news.tests.helpers import (
    create_news_for,
    create_partner_program,
    create_project,
    create_user,
)


class FeedAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="feed-user")
        self.client.force_authenticate(self.user)

    @staticmethod
    def get_feed_record(obj):
        return News.objects.get(
            content_type=ContentType.objects.get_for_model(obj),
            object_id=obj.pk,
            text=FEED_RECORD_TEXT,
        )

    def test_feed_returns_user_news_when_news_filter_requested(self):
        news = create_news_for(self.user, text="User feed news")

        response = self.client.get("/feed/?type=news")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(set(item.keys()), {"type_model", "content", "published_at"})
        self.assertEqual(item["type_model"], "news")
        self.assertEqual(item["content"]["id"], news.id)
        self.assertEqual(item["content"]["text"], "User feed news")
        self.assertEqual(item["published_at"], item["content"]["datetime_created"])

    def test_feed_returns_project_news_as_news_content(self):
        project = create_project(name="Feed project")
        news = create_news_for(project, text="Project feed news")

        response = self.client.get("/feed/?type=project")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(set(item.keys()), {"type_model", "content", "published_at"})
        self.assertEqual(item["type_model"], "news")
        self.assertEqual(item["content"]["id"], news.id)
        self.assertEqual(item["content"]["text"], "Project feed news")
        self.assertEqual(parse_datetime(item["published_at"]), news.datetime_created)

    def test_feed_ignores_program_news_filter(self):
        program = create_partner_program(name="Feed program")
        create_news_for(program, text="Program feed news")
        create_news_for(program, text="")

        response = self.client.get("/feed/?type=partnerprogram")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_feed_returns_project_feed_record_as_project_content(self):
        project = create_project(name="Feed record project")
        create_news_for_model(project)

        response = self.client.get("/feed/?type=project")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(set(item.keys()), {"type_model", "content", "published_at"})
        self.assertEqual(item["type_model"], "project")
        self.assertEqual(item["content"]["id"], project.id)
        self.assertEqual(
            parse_datetime(item["published_at"]),
            self.get_feed_record(project).datetime_created,
        )

    def test_feed_returns_vacancy_feed_record_as_vacancy_content(self):
        vacancy = create_vacancy(role="Backend developer")

        response = self.client.get("/feed/?type=vacancy")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(set(item.keys()), {"type_model", "content", "published_at"})
        self.assertEqual(item["type_model"], "vacancy")
        self.assertEqual(item["content"]["id"], vacancy.id)
        self.assertEqual(item["content"]["role"], "Backend developer")
        self.assertEqual(
            parse_datetime(item["published_at"]),
            self.get_feed_record(vacancy).datetime_created,
        )

    def test_category_counts_are_global_and_respect_visibility(self):
        project = create_project(name="Visible project")
        create_news_for(project, text="Visible project news")
        visible_vacancies = {
            create_vacancy(project=project, role="First visible vacancy").pk,
            create_vacancy(project=project, role="Second visible vacancy").pk,
        }
        create_news_for(self.user, text="Visible user news")
        create_news_for(
            create_project(name="Private project", is_public=False),
            text="Private project news",
        )
        create_news_for(
            create_project(name="Draft project", draft=True),
            text="Draft project news",
        )
        inactive_vacancy = create_vacancy(
            project=project,
            role="Inactive vacancy",
            is_active=False,
        )
        create_news_for_model(inactive_vacancy)
        create_news_for(create_partner_program(name="Program"), text="Program news")

        first_page = self.client.get("/feed/?type=vacancy&limit=1&offset=0")
        second_page = self.client.get("/feed/?type=vacancy&limit=1&offset=1")

        expected_counts = {
            "all": 5,
            "project": 2,
            "vacancy": 2,
            "news": 1,
            "partnerprogram": 0,
            "education": 0,
        }
        for response in (first_page, second_page):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                set(response.data),
                {"count", "next", "previous", "results", "counts"},
            )
            self.assertEqual(response.data["count"], 2)
            self.assertEqual(len(response.data["results"]), 1)
            self.assertEqual(response.data["counts"], expected_counts)
        self.assertEqual(
            {
                item["content"]["id"]
                for response in (first_page, second_page)
                for item in response.data["results"]
            },
            visible_vacancies,
        )

    def test_feed_uses_pk_as_tie_breaker_across_pages(self):
        news_items = [
            create_news_for(self.user, text=f"Same time {index}") for index in range(3)
        ]
        News.objects.filter(pk__in=[news.pk for news in news_items]).update(
            datetime_created=timezone.now()
        )

        first_page = self.client.get("/feed/?type=news&limit=2&offset=0")
        second_page = self.client.get("/feed/?type=news&limit=2&offset=2")

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(
            set(first_page.data),
            {
                "count",
                "next",
                "previous",
                "results",
                "counts",
            },
        )
        ordered_ids = [
            item["content"]["id"]
            for response in (first_page, second_page)
            for item in response.data["results"]
        ]
        self.assertEqual(
            ordered_ids,
            sorted((news.pk for news in news_items), reverse=True),
        )

    def test_feed_combines_supported_filters_and_ignores_program_news(self):
        project_news = create_news_for(
            create_project(name="Combined project news"),
            text="Combined project news",
        )
        program_news = create_news_for(
            create_partner_program(name="Combined program"),
            text="Combined program news",
        )
        user_news = create_news_for(self.user, text="Combined user news")
        project = create_project(name="Combined project record")
        vacancy = create_vacancy(role="Combined vacancy")
        create_news_for_model(project)

        response = self.client.get("/feed/?type=project|vacancy|news|partnerprogram")

        self.assertEqual(response.status_code, 200)
        items_by_text = {
            item["content"].get("text"): item
            for item in response.data["results"]
            if item["type_model"] == "news"
        }
        content_ids_by_type = {
            type_model: {
                item["content"]["id"]
                for item in response.data["results"]
                if item["type_model"] == type_model
            }
            for type_model in ["project", "vacancy"]
        }

        self.assertEqual(
            items_by_text[project_news.text]["content"]["id"],
            project_news.id,
        )
        self.assertEqual(
            items_by_text[user_news.text]["content"]["id"],
            user_news.id,
        )
        self.assertNotIn(program_news.text, items_by_text)
        self.assertIn(project.id, content_ids_by_type["project"])
        self.assertIn(vacancy.id, content_ids_by_type["vacancy"])

    def test_feed_excludes_feed_record_for_inactive_vacancy(self):
        vacancy = create_vacancy(role="Inactive vacancy", is_active=False)
        create_news_for_model(vacancy)

        response = self.client.get("/feed/?type=vacancy")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_feed_excludes_vacancy_feed_record_for_draft_project(self):
        draft_project = create_project(name="Draft vacancy project", draft=True)
        create_vacancy(project=draft_project, role="Draft project vacancy")

        response = self.client.get("/feed/?type=vacancy")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_feed_excludes_vacancy_feed_record_for_private_project(self):
        private_project = create_project(
            name="Private vacancy project",
            is_public=False,
        )
        create_vacancy(project=private_project, role="Private project vacancy")

        response = self.client.get("/feed/?type=vacancy")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_feed_marks_news_liked_by_current_user(self):
        news = create_news_for(self.user, text="Liked user feed news")
        set_like(news, self.user, True)

        response = self.client.get("/feed/?type=news")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(item["type_model"], "news")
        self.assertTrue(item["content"]["is_user_liked"])

    def test_feed_excludes_news_for_private_project(self):
        private_project = create_project(name="Private project", is_public=False)
        create_news_for(private_project, text="Private project news")

        response = self.client.get("/feed/?type=project")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_feed_excludes_news_for_draft_project(self):
        draft_project = create_project(name="Draft project", draft=True)
        create_news_for(draft_project, text="Draft project news")

        response = self.client.get("/feed/?type=project")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])
