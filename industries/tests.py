from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from users.models import CustomUser
from users.views import UserList

from industries.models import Industry
from industries.views import IndustryDetail, IndustryList


class IndustryTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

        self.user_list_view = UserList.as_view()

        self.industry_list_view = IndustryList.as_view()
        self.industry_detail_view = IndustryDetail.as_view()

        self.INDUSTRY_NAME = "Test Industry"
        self.CREATE_DATA = {
            "name": self.INDUSTRY_NAME,
        }

    def test_industry_creation(self):
        user = self._user_create()
        request = self.factory.post("industries/", self.CREATE_DATA)
        force_authenticate(request, user=user)
        response = self.industry_list_view(request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], self.INDUSTRY_NAME)

    def test_industry_creation_with_too_long_name(self):
        user = self._user_create()
        request = self.factory.post("industries/", {"name": "too_long_string_" * 257})
        force_authenticate(request, user=user)
        response = self.industry_list_view(request)
        self.assertEqual(response.status_code, 400)

    def test_industry_creation_with_empty_name(self):
        user = self._user_create()
        request = self.factory.post("industries/", {"name": ""})
        force_authenticate(request, user=user)
        response = self.industry_list_view(request)
        self.assertEqual(response.status_code, 400)

    def test_industry_creation_with_wrong_data(self):
        user = self._user_create()
        request = self.factory.post("industries/", {"wrong_name": "Wrong value"})
        force_authenticate(request, user=user)
        response = self.industry_list_view(request)
        self.assertEqual(response.status_code, 400)

    def test_industry_creation_with_empty_data(self):
        user = self._user_create()
        request = self.factory.post("industries/", {})
        force_authenticate(request, user=user)
        response = self.industry_list_view(request)
        self.assertEqual(response.status_code, 400)

    def test_industry_update(self):
        user = self._user_create()
        request = self.factory.post("industries/", self.CREATE_DATA)
        force_authenticate(request, user=user)
        response = self.industry_list_view(request)

        industry_id = response.data["id"]
        industry = Industry.objects.get(id=industry_id)

        request = self.factory.patch(f"industries/{industry.pk}/", {"name": "Test2"})
        force_authenticate(request, user=user)
        response = self.industry_detail_view(request, pk=industry.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Test2")

    def test_industry_update_with_wrong_data(self):
        user = self._user_create()
        request = self.factory.post("industries/", self.CREATE_DATA)
        force_authenticate(request, user=user)
        response = self.industry_list_view(request)

        industry_id = response.data["id"]
        industry = Industry.objects.get(id=industry_id)

        request = self.factory.patch(f"industries/{industry.pk}/", {"name": ""})
        force_authenticate(request, user=user)
        response = self.industry_detail_view(request, pk=industry.pk)

        self.assertEqual(response.status_code, 400)

    def _user_create(self):
        request = self.factory.post(
            "auth/users/",
            {
                "email": "only_for_test@test.test",
                "password": "test_password",
                "first_name": "Test_first_name",
                "last_name": "Test_last_name",
            },
        )
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)
        user.is_active = True
        user.save()
        return user
