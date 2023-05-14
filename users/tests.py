from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from tests.constants import USER_CREATE_DATA

from users.models import CustomUser
from users.views import UserList, UserDetail, LogoutView


class UserTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user_list_view = UserList.as_view()
        self.user_detail_view = UserDetail.as_view()
        self.logout_view = LogoutView.as_view()

    def test_user_creation(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
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
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        self.assertEqual(response.status_code, 201)
        response = self.user_list_view(request)
        self.assertEqual(response.status_code, 400)

    def test_user_update(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)

        request = self.factory.get(f"auth/users/{user.pk}/")
        response = self.user_detail_view(request, pk=user.pk)
        self.assertEqual(response.status_code, 401)  # Unauthorized

        force_authenticate(request, user=user)
        response = self.user_detail_view(request, pk=user.pk)
        self.assertEqual(response.status_code, 200)

        request = self.factory.patch(f"auth/users/{user.pk}/", {"first_name": "Test2"})
        force_authenticate(request, user=user)
        response = self.user_detail_view(request, pk=user.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["first_name"], "Test2")

    def test_user_logout(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)

        request = self.factory.get("auth/users/projects/")
        response = self.user_detail_view(request, pk=user.pk)
        self.assertEqual(response.status_code, 401)

        force_authenticate(request, user=user)
        response = self.user_detail_view(request, pk=user.pk)
        self.assertEqual(response.status_code, 200)

        test_refresh_token = "test_refresh_token"
        request = self.factory.post("auth/logout/", {"refresh_token": test_refresh_token})
        force_authenticate(request, user=user)
        response = self.logout_view(request, testing=True)
        self.assertEqual(response.status_code, 205)

        request = self.factory.get("auth/users/projects/")
        response = self.user_detail_view(request)
        self.assertEqual(response.status_code, 401)

    def test_change_user_type_invalid(self):
        request = self.factory.post("auth/users/", USER_CREATE_DATA)
        response = self.user_list_view(request)
        user_id = response.data["id"]
        user = CustomUser.objects.get(id=user_id)

        invalid_user_type = "invalid_type"
        request = self.factory.patch(
            f"auth/users/{user.pk}/", {"user_type": invalid_user_type}
        )
        force_authenticate(request, user=user)
        response = self.user_detail_view(request, pk=user.pk)

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertNotEqual(user.user_type, invalid_user_type)
