from django.test import TestCase

from feed.tests.helpers import create_vacancy
from news.models import News
from news.services import FEED_RECORD_TEXT
from news.tests.helpers import create_project


class FeedSignalTests(TestCase):
    def test_project_signal_removes_feed_record_when_project_becomes_draft(self):
        project = create_project(name="Draft signal project")
        self.assertTrue(
            News.objects.get_news(project).filter(text=FEED_RECORD_TEXT).exists()
        )

        project.draft = True
        project.save(update_fields=["draft"])

        self.assertFalse(
            News.objects.get_news(project).filter(text=FEED_RECORD_TEXT).exists()
        )

    def test_project_delete_signal_removes_feed_record(self):
        project = create_project(name="Deleted signal project")
        project_id = project.id

        project.delete()

        self.assertFalse(
            News.objects.filter(
                object_id=project_id,
                content_type__model="project",
                text=FEED_RECORD_TEXT,
            ).exists()
        )

    def test_vacancy_signal_creates_and_removes_feed_record_by_active_state(self):
        vacancy = create_vacancy(role="Signal vacancy")
        self.assertTrue(
            News.objects.get_news(vacancy).filter(text=FEED_RECORD_TEXT).exists()
        )

        vacancy.is_active = False
        vacancy.save(update_fields=["is_active"])

        self.assertFalse(
            News.objects.get_news(vacancy).filter(text=FEED_RECORD_TEXT).exists()
        )

    def test_vacancy_delete_signal_removes_feed_record(self):
        vacancy = create_vacancy(role="Deleted signal vacancy")
        vacancy_id = vacancy.id

        vacancy.delete()

        self.assertFalse(
            News.objects.filter(
                object_id=vacancy_id,
                content_type__model="vacancy",
                text=FEED_RECORD_TEXT,
            ).exists()
        )
