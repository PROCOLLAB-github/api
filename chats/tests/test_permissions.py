from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from chats.models import ProjectChat
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from chats.views import ProjectChatDetail
from projects.models import Collaborator, Project


@override_settings(ALLOWED_HOSTS=["testserver", "dev.procollab.ru", "127.0.0.1"])
class ChatPermissionsTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.leader = get_user_model().objects.create(**TEST_USER1)
        self.collaborator = get_user_model().objects.create(**TEST_USER2)
        self.outsider = get_user_model().objects.create(**TEST_USER3)
        self.project = Project.objects.create(leader=self.leader)
        self.chat = ProjectChat.objects.create(project=self.project)
        Collaborator.objects.create(
            user=self.collaborator,
            project=self.project,
            role="User",
        )

        self.staff = get_user_model().objects.create(
            email="swagger-staff@test.test",
            password="very_strong_password",
            first_name="Swagger",
            last_name="Staff",
            birthday="2000-01-01",
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )
        self.staff.set_password("very_strong_password")
        self.staff.save()

    def test_swagger_schema_is_available_for_staff(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            "/swagger/?format=openapi",
            secure=True,
            HTTP_HOST="dev.procollab.ru",
        )

        self.assertEqual(response.status_code, 200)

    def test_project_chat_detail_is_available_for_leader(self):
        request = self.factory.get(f"/chats/projects/{self.chat.id}/")
        force_authenticate(request, user=self.leader)

        response = ProjectChatDetail.as_view()(request, pk=self.chat.id)

        self.assertEqual(response.status_code, 200)

    def test_project_chat_detail_is_available_for_collaborator(self):
        request = self.factory.get(f"/chats/projects/{self.chat.id}/")
        force_authenticate(request, user=self.collaborator)

        response = ProjectChatDetail.as_view()(request, pk=self.chat.id)

        self.assertEqual(response.status_code, 200)

    def test_project_chat_detail_is_forbidden_for_outsider(self):
        request = self.factory.get(f"/chats/projects/{self.chat.id}/")
        force_authenticate(request, user=self.outsider)

        response = ProjectChatDetail.as_view()(request, pk=self.chat.id)

        self.assertEqual(response.status_code, 403)
