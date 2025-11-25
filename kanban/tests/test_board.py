from django.core.exceptions import ValidationError

from kanban.models import Board, BoardColumn
from kanban.tests.base import BaseKanbanTestCase


class BoardModelTests(BaseKanbanTestCase):
    def test_project_cannot_have_more_than_five_boards(self):
        existing = Board.objects.filter(project=self.project).count()
        for index in range(Board.MAX_PER_PROJECT - existing):
            Board.objects.create(project=self.project, name=f"Board {index}")

        with self.assertRaises(ValidationError):
            Board.objects.create(project=self.project, name="Overflow")


class BoardColumnTests(BaseKanbanTestCase):
    def test_columns_require_unique_order_and_name_per_board(self):
        duplicate_order = BoardColumn(board=self.board, name="In progress", order=self.column.order)
        with self.assertRaises(ValidationError):
            duplicate_order.full_clean()

        duplicate_name = BoardColumn(board=self.board, name=self.column.name, order=2)
        with self.assertRaises(ValidationError):
            duplicate_name.full_clean()

    def test_get_tasks_count_returns_cached_value(self):
        column = BoardColumn.objects.create(
            board=self.board,
            name="QA",
            order=2,
            tasks_count=7,
        )

        self.assertEqual(column.get_tasks_count(), 7)

    def test_cannot_delete_last_column(self):
        # board already has at least one column (self.column)
        with self.assertRaises(ValidationError):
            self.column.delete()

        extra = BoardColumn.objects.create(board=self.board, name="Extra", order=99)
        extra.delete()  # should not raise
        # still at least one column remains
        self.assertGreaterEqual(self.board.columns.count(), 1)
