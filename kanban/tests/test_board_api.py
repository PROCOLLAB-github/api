from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from kanban.models import Board
from kanban.tests.base import BaseKanbanTestCase
from projects.models import Project
from users.models import CustomUser


class BoardAPITests(BaseKanbanTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("kanban:kanban-board-list")

    def test_list_boards_returns_user_project_boards(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["project"], self.project.id)

    def test_create_board_creates_backlog_column(self):
        payload = {
            "project": self.project.id,
            "name": "New Board",
            "color": "blue",
            "icon": "rocket",
            "description": "",
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        board_id = response.data["id"]
        board = Board.objects.get(id=board_id)
        backlog = board.columns.first()
        self.assertIsNotNone(backlog)
        self.assertEqual(backlog.name, "Бэклог")

    def test_cannot_create_board_for_foreign_project(self):
        foreign_leader = CustomUser.objects.create(
            email="foreign@example.com",
            first_name="Foreign",
            last_name="Leader",
            password="pass1234",
            birthday=self.user.birthday,
        )
        foreign_project = Project.objects.create(name="Foreign", leader=foreign_leader)
        payload = {
            "project": foreign_project.id,
            "name": "Forbidden",
            "color": "blue",
            "icon": "rocket",
            "description": "",
        }
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
