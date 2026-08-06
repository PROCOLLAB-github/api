from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Like, View
from feed.services import create_news_for_model
from news.models import News, NewsComment
from news.tests.helpers import (
    create_news_for,
    create_partner_program,
    create_project,
    create_user,
    create_user_file,
)
from partner_programs.models import PartnerProgramUserProfile


class ReactNewsFeedAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="react-feed-user")
        self.client.force_authenticate(self.user)

    def test_authentication_is_required(self):
        self.client.force_authenticate(user=None)

        response = self.client.get("/feed/news/")

        self.assertEqual(response.status_code, 401)

    def test_program_is_default_source_and_participant_news_is_excluded(self):
        program = create_partner_program(name="Default feed program")
        platform_news = create_news_for(
            program,
            text="Platform program post",
            audience=News.Audience.PLATFORM,
        )
        create_news_for(
            program,
            text="Internal program post",
            audience=News.Audience.PROGRAM_PARTICIPANTS,
        )
        create_news_for(self.user, text="User post")

        response = self.client.get("/feed/news/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [platform_news.pk],
        )
        self.assertEqual(response.data["results"][0]["source_type"], "program")

    def test_each_source_returns_only_its_publications(self):
        program_news = create_news_for(
            create_partner_program(name="Source program"),
            text="Program source post",
        )
        project_news = create_news_for(
            create_project(name="Source project"),
            text="Project source post",
        )
        user_news = create_news_for(self.user, text="User source post")

        expected = {
            "program": program_news.pk,
            "project": project_news.pk,
            "user": user_news.pk,
        }
        for source, news_id in expected.items():
            with self.subTest(source=source):
                response = self.client.get(f"/feed/news/?source={source}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [item["id"] for item in response.data["results"]],
                    [news_id],
                )

    def test_service_records_and_unavailable_projects_are_excluded(self):
        public_project = create_project(name="Public publication")
        public_news = create_news_for(public_project, text="Visible project post")
        create_news_for_model(public_project)
        create_news_for(
            create_project(name="Private publication", is_public=False),
            text="Private project post",
        )
        create_news_for(
            create_project(name="Draft publication", draft=True),
            text="Draft project post",
        )

        response = self.client.get("/feed/news/?source=project")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [public_news.pk],
        )

    def test_results_are_newest_first_and_paginated(self):
        program = create_partner_program(name="Ordered program")
        oldest = create_news_for(program, text="Oldest")
        middle = create_news_for(program, text="Middle")
        newest = create_news_for(program, text="Newest")
        now = timezone.now()
        News.objects.filter(pk=oldest.pk).update(datetime_created=now - timedelta(days=2))
        News.objects.filter(pk=middle.pk).update(datetime_created=now - timedelta(days=1))
        News.objects.filter(pk=newest.pk).update(datetime_created=now)

        first_page = self.client.get("/feed/news/?limit=2&offset=0")
        second_page = self.client.get("/feed/news/?limit=2&offset=2")

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.data["count"], 3)
        self.assertEqual(
            [item["id"] for item in first_page.data["results"]],
            [newest.pk, middle.pk],
        )
        self.assertEqual(
            [item["id"] for item in second_page.data["results"]],
            [oldest.pk],
        )

    def test_search_matches_text_and_source_name_inside_selected_tab(self):
        matching_program = create_partner_program(name="Quantum accelerator")
        name_match = create_news_for(matching_program, text="General update")
        text_match = create_news_for(
            create_partner_program(name="Other program"),
            text="Quantum milestone",
        )
        create_news_for(
            create_partner_program(name="Unrelated program"),
            text="Nothing relevant",
        )
        create_news_for(self.user, text="Quantum user post")

        response = self.client.get("/feed/news/?source=program&search=  Quantum  ")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.data["results"]},
            {name_match.pk, text_match.pk},
        )

    def _assert_user_search_matches(self, search):
        matching_user = create_user(prefix="react-feed-name-match")
        matching_user.first_name = "Анна"
        matching_user.last_name = "Иванова"
        matching_user.save(update_fields=["first_name", "last_name"])
        matching_news = create_news_for(
            matching_user,
            text="Нейтральная публикация",
        )
        create_news_for(
            create_user(prefix="react-feed-name-other"),
            text="Другая публикация",
        )

        response = self.client.get(
            "/feed/news/",
            {"source": "user", "search": search},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data["results"]],
            [matching_news.pk],
        )

    def test_user_search_matches_first_name(self):
        self._assert_user_search_matches("Анна")

    def test_user_search_matches_last_name(self):
        self._assert_user_search_matches("Иванова")

    def test_user_search_matches_full_name(self):
        self._assert_user_search_matches("Анна Иванова")

    def test_user_search_matches_reversed_full_name(self):
        self._assert_user_search_matches("Иванова Анна")

    def test_unknown_source_and_excessive_search_are_rejected(self):
        unknown_source = self.client.get("/feed/news/?source=vacancy")
        long_search = self.client.get(f"/feed/news/?search={'x' * 201}")

        self.assertEqual(unknown_source.status_code, 400)
        self.assertIn("source", unknown_source.data)
        self.assertEqual(long_search.status_code, 400)
        self.assertIn("search", long_search.data)

    def test_unified_response_contains_files_counts_and_like_state(self):
        program = create_partner_program(name="Contract program")
        file = create_user_file(self.user)
        news = create_news_for(
            program,
            text="Contract post",
            files=[file],
        )
        content_type = ContentType.objects.get_for_model(News)
        Like.objects.create(
            user=self.user,
            content_type=content_type,
            object_id=news.pk,
        )
        View.objects.create(
            user=self.user,
            content_type=content_type,
            object_id=news.pk,
        )
        NewsComment.objects.create(news=news, author=self.user, text="Comment")

        response = self.client.get("/feed/news/")

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(
            set(item),
            {
                "id",
                "source_type",
                "source",
                "text",
                "files",
                "audience",
                "datetime_created",
                "datetime_updated",
                "likes_count",
                "comments_count",
                "views_count",
                "is_user_liked",
            },
        )
        self.assertEqual(item["source"]["id"], program.pk)
        self.assertEqual(item["source"]["name"], program.name)
        self.assertEqual(item["files"][0]["link"], file.link)
        self.assertEqual(item["likes_count"], 1)
        self.assertEqual(item["comments_count"], 1)
        self.assertEqual(item["views_count"], 1)
        self.assertTrue(item["is_user_liked"])

    def test_list_query_count_does_not_grow_per_publication(self):
        program = create_partner_program(name="Query budget program")
        for index in range(5):
            create_news_for(program, text=f"Query post {index}")
        ContentType.objects.get_for_model(News)
        ContentType.objects.get_for_model(type(program))

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get("/feed/news/?limit=10")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 5)
        self.assertLessEqual(len(captured), 8)


class ReactNewsInteractionAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="react-interaction-user")
        self.other_user = create_user(prefix="react-interaction-other")
        self.program = create_partner_program(name="Interaction program")
        self.news = create_news_for(self.program, text="Interactive post")
        self.client.force_authenticate(self.user)

    def test_like_and_unlike_are_idempotent_and_user_specific(self):
        like_url = f"/feed/news/{self.news.pk}/set-liked/"

        first = self.client.post(like_url, {"is_liked": True}, format="json")
        repeated = self.client.post(like_url, {"is_liked": True}, format="json")
        self.client.force_authenticate(self.other_user)
        other = self.client.post(like_url, {"is_liked": True}, format="json")
        self.client.force_authenticate(self.user)
        unlike = self.client.post(like_url, {"is_liked": False}, format="json")

        self.assertEqual(first.data, {"is_user_liked": True, "likes_count": 1})
        self.assertEqual(
            repeated.data,
            {"is_user_liked": True, "likes_count": 1},
        )
        self.assertEqual(other.data["likes_count"], 2)
        self.assertEqual(
            unlike.data,
            {"is_user_liked": False, "likes_count": 1},
        )

    def test_view_is_idempotent(self):
        url = f"/feed/news/{self.news.pk}/set-viewed/"

        first = self.client.post(url, {}, format="json")
        repeated = self.client.post(url, {}, format="json")

        self.assertEqual(first.data, {"views_count": 1})
        self.assertEqual(repeated.data, {"views_count": 1})

    def test_inaccessible_news_cannot_be_opened_liked_or_viewed(self):
        internal = create_news_for(
            self.program,
            text="Internal interaction",
            audience=News.Audience.PROGRAM_PARTICIPANTS,
        )

        detail = self.client.get(f"/feed/news/{internal.pk}/")
        liked = self.client.post(
            f"/feed/news/{internal.pk}/set-liked/",
            {"is_liked": True},
            format="json",
        )
        viewed = self.client.post(
            f"/feed/news/{internal.pk}/set-viewed/",
            {},
            format="json",
        )

        self.assertEqual(detail.status_code, 404)
        self.assertEqual(liked.status_code, 404)
        self.assertEqual(viewed.status_code, 404)

    def test_participant_can_open_internal_program_news_by_detail_link(self):
        internal = create_news_for(
            self.program,
            audience=News.Audience.PROGRAM_PARTICIPANTS,
        )
        PartnerProgramUserProfile.objects.create(
            partner_program=self.program,
            user=self.user,
            partner_program_data={},
        )

        response = self.client.get(f"/feed/news/{internal.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], internal.pk)

    def test_empty_service_record_cannot_be_opened(self):
        project = create_project(name="Hidden service record")
        create_news_for_model(project)
        service_record = News.objects.get_news(project).get(text="")

        response = self.client.get(f"/feed/news/{service_record.pk}/")

        self.assertEqual(response.status_code, 404)
