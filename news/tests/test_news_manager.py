from django.test import TestCase

from news.models import News

from .helpers import create_news_for, create_project, create_user_file


class NewsManagerTests(TestCase):
    def test_add_news_binds_news_to_content_object_and_files(self):
        project = create_project()
        file = create_user_file(project.leader)

        news = News.objects.add_news(
            project,
            text="Project update",
            files=[file],
        )

        self.assertEqual(news.content_object, project)
        self.assertEqual(news.text, "Project update")
        self.assertEqual(list(news.files.all()), [file])

    def test_get_news_returns_only_news_for_requested_object(self):
        project = create_project(name="Target project")
        other_project = create_project(name="Other project")
        target_news = create_news_for(project, text="Target news")
        create_news_for(other_project, text="Other news")

        queryset = News.objects.get_news(project).filter(text="Target news")

        self.assertEqual(list(queryset), [target_news])
