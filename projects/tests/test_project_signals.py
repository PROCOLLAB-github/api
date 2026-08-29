from unittest.mock import patch

from django.test import TestCase

from chats.models import ProjectChat
from news.models import News

from .helpers import create_project, create_vacancy


class ProjectDraftSignalRegressionTests(TestCase):
    def test_publish_project_activates_vacancies_creates_feed_news_and_chat(self):
        project = create_project(draft=True)
        vacancy = create_vacancy(project, is_active=False)

        project.draft = False
        project.save()

        vacancy.refresh_from_db()
        self.assertTrue(vacancy.is_active)
        self.assertIsNone(vacancy.datetime_closed)
        self.assertTrue(News.objects.get_news(vacancy).filter(text="").exists())
        self.assertTrue(ProjectChat.objects.filter(project=project).exists())

    def test_return_project_to_draft_deactivates_vacancies_and_removes_feed_news(self):
        project = create_project(draft=False)
        vacancy = create_vacancy(project, is_active=True)

        self.assertTrue(News.objects.get_news(vacancy).filter(text="").exists())

        project.draft = True
        project.save()

        vacancy.refresh_from_db()
        self.assertFalse(vacancy.is_active)
        self.assertIsNotNone(vacancy.datetime_closed)
        self.assertFalse(News.objects.get_news(vacancy).filter(text="").exists())

    def test_save_published_project_does_not_change_active_vacancy(self):
        project = create_project(draft=False)
        vacancy = create_vacancy(project, is_active=True)

        project.description = "Updated description"
        with patch("projects.signals.create_news_for_model") as create_news, patch(
            "projects.signals.delete_news_for_model"
        ) as delete_news:
            project.save()

        vacancy.refresh_from_db()
        self.assertTrue(vacancy.is_active)
        self.assertIsNone(vacancy.datetime_closed)
        create_news.assert_not_called()
        delete_news.assert_not_called()

    def test_save_published_project_does_not_reopen_closed_vacancy(self):
        project = create_project(draft=False)
        vacancy = create_vacancy(project, is_active=False)
        closed_at = vacancy.datetime_closed

        project.description = "Updated description"
        with patch("projects.signals.create_news_for_model") as create_news, patch(
            "projects.signals.delete_news_for_model"
        ) as delete_news:
            project.save()

        vacancy.refresh_from_db()
        self.assertFalse(vacancy.is_active)
        self.assertEqual(vacancy.datetime_closed, closed_at)
        create_news.assert_not_called()
        delete_news.assert_not_called()

    def test_draft_transition_updates_feed_only_for_changed_vacancies(self):
        project = create_project(draft=False)
        active = create_vacancy(project, is_active=True)
        closed = create_vacancy(project, is_active=False)

        project.draft = True
        with patch("projects.signals.create_news_for_model") as create_news, patch(
            "projects.signals.delete_news_for_model"
        ) as delete_news:
            project.save(update_fields=("draft",))

        active.refresh_from_db()
        closed.refresh_from_db()
        self.assertFalse(active.is_active)
        self.assertFalse(closed.is_active)
        self.assertIsNotNone(active.datetime_closed)
        self.assertIsNotNone(closed.datetime_closed)
        create_news.assert_not_called()
        delete_news.assert_called_once_with(active)

    def test_repeated_publish_does_not_duplicate_feed_news_or_chat(self):
        project = create_project(draft=True)
        vacancy = create_vacancy(project, is_active=False)

        project.draft = False
        project.save()
        project.save()

        self.assertEqual(News.objects.get_news(vacancy).filter(text="").count(), 1)
        self.assertEqual(ProjectChat.objects.filter(project=project).count(), 1)
