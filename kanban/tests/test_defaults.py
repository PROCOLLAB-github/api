from django.core.exceptions import ValidationError

from kanban.tests.base import BaseKanbanTestCase
from projects.models import Project


class DefaultBoardCreationTests(BaseKanbanTestCase):
    def test_project_creates_default_board_and_backlog(self):
        project = Project.objects.create(name="Signal Project", leader=self.user)
        board = project.kanban_boards.first()
        self.assertIsNotNone(board)
        self.assertEqual(board.name, project.name)
        backlog = board.columns.first()
        self.assertIsNotNone(backlog)
        self.assertEqual(backlog.name, "Бэклог")
        self.assertEqual(backlog.order, 1)

    def test_cannot_delete_last_column(self):
        board = self.board
        # ensure only one column exists
        board.columns.exclude(pk=self.column.pk).delete()
        with self.assertRaisesMessage(
            ValidationError, "Нельзя удалить последнюю колонку на доске."
        ):
            self.column.delete()
