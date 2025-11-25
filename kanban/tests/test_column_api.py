from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from kanban.models import Board, BoardColumn
from kanban.tests.base import BaseKanbanTestCase
from projects.models import Project
from users.models import CustomUser


class ColumnAPITests(BaseKanbanTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("kanban:kanban-column-list")

    def test_list_columns_returns_board_columns(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["board_id"], self.board.id)

    def test_create_column(self):
        payload = {"board": self.board.id, "name": "In Progress"}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        column_id = response.data["id"]
        column = BoardColumn.objects.get(id=column_id)
        self.assertEqual(column.name, "In Progress")
        self.assertEqual(column.order, self.board.columns.count())

    def test_cannot_create_column_in_foreign_project(self):
        foreign_leader = CustomUser.objects.create(
            email="foreign@example.com",
            first_name="Foreign",
            last_name="Leader",
            password="pass1234",
            birthday=self.user.birthday,
        )
        foreign_project = Project.objects.create(name="Foreign", leader=foreign_leader)
        foreign_board = Board.objects.create(
            project=foreign_project, name="Foreign Board"
        )
        payload = {"board": foreign_board.id, "name": "Forbidden"}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_delete_last_column(self):
        self.board.columns.exclude(pk=self.column.pk).delete()
        col_url = reverse("kanban:kanban-column-detail", args=[self.column.id])
        response = self.client.delete(col_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
