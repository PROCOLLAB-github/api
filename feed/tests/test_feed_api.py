from django.test import TestCase
from rest_framework.test import APIClient

from core.services import set_like
from feed.services import create_news_for_model
from feed.tests.helpers import create_vacancy
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

    def test_feed_returns_user_news_when_news_filter_requested(self):
        news = create_news_for(self.user, text="User feed news")

        response = self.client.get("/feed/?type=news")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(set(item.keys()), {"type_model", "content"})
        self.assertEqual(item["type_model"], "news")
        self.assertEqual(item["content"]["id"], news.id)
        self.assertEqual(item["content"]["text"], "User feed news")

    def test_feed_returns_project_news_as_news_content(self):
        project = create_project(name="Feed project")
        news = create_news_for(project, text="Project feed news")

        response = self.client.get("/feed/?type=project")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(set(item.keys()), {"type_model", "content"})
        self.assertEqual(item["type_model"], "news")
        self.assertEqual(item["content"]["id"], news.id)
        self.assertEqual(item["content"]["text"], "Project feed news")

    def test_feed_returns_program_news_as_news_content(self):
        program = create_partner_program(name="Feed program")
        news = create_news_for(program, text="Program feed news")

        response = self.client.get("/feed/?type=partnerprogram")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(set(item.keys()), {"type_model", "content"})
        self.assertEqual(item["type_model"], "news")
        self.assertEqual(item["content"]["id"], news.id)
        self.assertEqual(item["content"]["text"], "Program feed news")

    def test_feed_returns_project_feed_record_as_project_content(self):
        project = create_project(name="Feed record project")
        create_news_for_model(project)

        response = self.client.get("/feed/?type=project")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(set(item.keys()), {"type_model", "content"})
        self.assertEqual(item["type_model"], "project")
        self.assertEqual(item["content"]["id"], project.id)

    def test_feed_returns_vacancy_feed_record_as_vacancy_content(self):
        vacancy = create_vacancy(role="Backend developer")

        response = self.client.get("/feed/?type=vacancy")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(set(item.keys()), {"type_model", "content"})
        self.assertEqual(item["type_model"], "vacancy")
        self.assertEqual(item["content"]["id"], vacancy.id)
        self.assertEqual(item["content"]["role"], "Backend developer")

    def test_feed_combines_all_supported_filters(self):
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

        response = self.client.get(
            "/feed/?type=project|vacancy|news|partnerprogram"
        )

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
            items_by_text[program_news.text]["content"]["id"],
            program_news.id,
        )
        self.assertEqual(
            items_by_text[user_news.text]["content"]["id"],
            user_news.id,
        )
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
