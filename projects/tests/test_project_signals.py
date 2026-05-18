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
        self.assertFalse(News.objects.get_news(vacancy).filter(text="").exists())

    def test_repeated_publish_does_not_duplicate_feed_news_or_chat(self):
        project = create_project(draft=True)
        vacancy = create_vacancy(project, is_active=False)

        project.draft = False
        project.save()
        project.save()

        self.assertEqual(News.objects.get_news(vacancy).filter(text="").count(), 1)
        self.assertEqual(ProjectChat.objects.filter(project=project).count(), 1)
