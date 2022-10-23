from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from users.models import CustomUser
from users.views import UserList, UserDetail


class UserTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user_list_view = UserList.as_view()
        self.user_detail_view = UserDetail.as_view()
        self.user_create_data = {
            "email": "only_for_test@test.test",
            "password": "very_strong_password",
            "first_name": "Test",
            "last_name": "Test",
        }

    def test_user_creation(self):
        request = self.factory.post("auth/users/", self.user_create_data)
        response = self.user_list_view(request)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["email"], "only_for_test@test.test")
        self.assertEqual(response.data["is_active"], False)

    def test_user_creation_with_wrong_data(self):
        request = self.factory.post(
            "auth/users/",
            {
                "email": "qwe",
                "password": "qwe",
                "first_name": "qwe",
                "last_name": "qwe",
            },
        )
        response = self.user_list_view(request)
        self.assertEqual(response.status_code, 400)

    def test_user_creation_with_existing_email(self):
        request = self.factory.post("auth/users/", self.user_create_data)
        response = self.user_list_view(request)
        self.assertEqual(response.status_code, 201)
        response = self.user_list_view(request)
        self.assertEqual(response.status_code, 400)

    def test_user_detail_view(self):
        request = self.factory.post("auth/users/", self.user_create_data)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)

        request = self.factory.get(f"auth/users/{user.pk}/")
        response = self.user_detail_view(request, pk=user.pk)
        self.assertEqual(response.status_code, 401)  # Unauthorized

        force_authenticate(request, user=user)
        response = self.user_detail_view(request, pk=user.pk)
        self.assertEqual(response.status_code, 200)
