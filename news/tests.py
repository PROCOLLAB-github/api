# from django.test import TestCase
# from rest_framework.test import APIRequestFactory, force_authenticate
# from tests.constants import USER_CREATE_DATA
# from users.models import CustomUser
# from users.views import UserList
#
# from news.models import News
# from news.views import NewsDetail, NewsList
#
#
# class NewsTestCase(TestCase):
#     def setUp(self):
#         self.factory = APIRequestFactory()
#
#         self.user_list_view = UserList.as_view()
#
#         self.news_list_view = NewsList.as_view()
#         self.news_detail_view = NewsDetail.as_view()
#
#         self.TITLE = "Test News title"
#         self.TEXT = "Test News text"
#         self.SHORT_TEXT = "Test News short text"
#         self.COVER_URL = "https://example.com/"
#
#         self.CREATE_DATA = {
#             "title": self.TITLE,
#             "text": self.TEXT,
#             "short_text": self.SHORT_TEXT,
#             "cover_url": self.COVER_URL,
#         }
#
#     def test_news_creation(self):
#         user = self._user_create(is_staff=True)
#         request = self.factory.post("news/", self.CREATE_DATA)
#         force_authenticate(request, user=user)
#         response = self.news_list_view(request)
#
#         self.assertEqual(response.status_code, 201)
#         self.assertEqual(response.data["title"], self.TITLE)
#         self.assertEqual(response.data["short_text"], self.SHORT_TEXT)
#         self.assertEqual(response.data["cover_url"], self.COVER_URL)
#
#     def test_news_creation_by_not_staff_user(self):
#         user = self._user_create(is_staff=False)
#         request = self.factory.post("news/", self.CREATE_DATA)
#         force_authenticate(request, user=user)
#         response = self.news_list_view(request)
#
#         self.assertEqual(response.status_code, 403)
#
#     def test_news_creation_with_too_long_title(self):
#         user = self._user_create(is_staff=True)
#         new_data = self.CREATE_DATA
#         new_data["title"] = "too_long_string_" * 257
#
#         request = self.factory.post("news/", new_data)
#         force_authenticate(request, user=user)
#         response = self.news_list_view(request)
#         self.assertEqual(response.status_code, 400)
#
#     def test_news_creation_with_empty_title(self):
#         user = self._user_create(is_staff=True)
#         new_data = self.CREATE_DATA
#         new_data["title"] = ""
#
#         request = self.factory.post("news/", new_data)
#         force_authenticate(request, user=user)
#         response = self.news_list_view(request)
#         self.assertEqual(response.status_code, 400)
#
#     def test_news_creation_with_wrong_data(self):
#         user = self._user_create(is_staff=True)
#         request = self.factory.post("news/", {"wrong_field": "wrong_value"})
#
#         force_authenticate(request, user=user)
#         response = self.news_list_view(request)
#         self.assertEqual(response.status_code, 400)
#
#     def test_news_creation_with_empty_data(self):
#         user = self._user_create(is_staff=True)
#         request = self.factory.post("news/", {})
#
#         force_authenticate(request, user=user)
#         response = self.news_list_view(request)
#         self.assertEqual(response.status_code, 400)
#
#     def test_news_update(self):
#         user = self._user_create(is_staff=True)
#         request = self.factory.post("news/", self.CREATE_DATA)
#         force_authenticate(request, user=user)
#         response = self.news_list_view(request)
#
#         news_id = response.data["id"]
#         news = News.objects.get(id=news_id)
#
#         request = self.factory.patch(f"news/{news.pk}/", {"title": "New title"})
#         force_authenticate(request, user=user)
#         response = self.news_detail_view(request, pk=news.pk)
#
#         self.assertEqual(response.status_code, 200)
#         self.assertEqual(response.data["title"], "New title")
#
#     def test_news_update_with_wrong_data(self):
#         user = self._user_create(is_staff=True)
#         request = self.factory.post("news/", self.CREATE_DATA)
#         force_authenticate(request, user=user)
#         response = self.news_list_view(request)
#
#         news_id = response.data["id"]
#         news = News.objects.get(id=news_id)
#
#         new_data = self.CREATE_DATA
#         new_data["title"] = ""
#
#         request = self.factory.patch(f"news/{news.pk}/", new_data)
#         force_authenticate(request, user=user)
#         response = self.news_detail_view(request, pk=news.pk)
#
#         self.assertEqual(response.status_code, 400)
#
#     def _user_create(self, is_staff=False):
#         request = self.factory.post("auth/users/", USER_CREATE_DATA)
#         response = self.user_list_view(request)
#         user_id = response.data["id"]
#         user = CustomUser.objects.get(id=user_id)
#         user.is_staff = is_staff
#         user.is_active = True
#         user.save()
#         return user
