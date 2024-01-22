from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from tests.constants import USER_CREATE_DATA

from industries.models import Industry
from news.models import News
from news.views import NewsList
from users.models import CustomUser
from users.views import UserList
from projects.models import Project
from projects.views import ProjectList


class NewsTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.news_list_view = NewsList.as_view()
        self.user_list_view = UserList.as_view()
        self.project_list_view = ProjectList.as_view()
        self.project_create_data = {
            "name": "Test Project",
            "description": "Test Description",
            "industry": Industry.objects.create(name="Test Industry").id,
            "step": 1,
        }
        self.user = self.user_create()
        self.project = self.create_project(self.user, self.project_create_data)
        self.news = self.create_news(
            self.user, self.project, {"title": "Test News", "content": "Test Content"}
        )

    def test_news_creation(self):
        news_data = {
            "title": "Test News",
            "content": "Test Content",
            "project": self.project.pk,
        }

        request = self.factory.post("news/", news_data)
        force_authenticate(request, user=self.user)

        response = self.news_list_view(request)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["title"], "Test News")
        self.assertEqual(response.data["content"], "Test Content")
        self.assertEqual(response.data["project"], self.project.pk)

    def test_news_creation_with_wrong_data(self):
        news_data = {
            "title": "T" * 257,
            "content": "Test Content",
            "project": self.project.pk,
        }

        request = self.factory.post("news/", news_data)
        force_authenticate(request, user=self.user)

        response = self.news_list_view(request)
        self.assertEqual(response.status_code, 400)

    def test_news_deletion(self):
        request = self.factory.delete(f"news/{self.news.pk}/")
        force_authenticate(request, user=self.user)

        response = self.news_list_view(request)
        self.assertEqual(response.status_code, 204)

    def create_project(self, user, project_data):
        request = self.factory.post("projects/", project_data)
        force_authenticate(request, user=user)

        response = self.project_list_view(request)
        project_id = response.data["id"]
        return Project.objects.get(id=project_id)

    def create_news(self, user, project, news_data):
        request = self.factory.post("news/", news_data)
        force_authenticate(request, user=user)

        response = self.news_list_view(request)
        news_id = response.data["id"]
        return News.objects.get(id=news_id)

    def user_create(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user
