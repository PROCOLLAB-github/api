from datetime import date

from django.test import TestCase

from core.models import SkillCategory
from projects.models import Project
from users.models import CustomUser

from kanban.models import Board, BoardColumn


class BaseKanbanTestCase(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create(
            email="leader@example.com",
            first_name="Leader",
            last_name="User",
            password="pass1234",
            birthday=date(2000, 1, 1),
        )
        self.project = Project.objects.create(
            name="Test Project",
            leader=self.user,
        )
        # Signal can create default board/column; reuse if exists.
        self.board = (
            Board.objects.filter(project=self.project).first()
            or Board.objects.create(project=self.project, name=self.project.name)
        )
        self.column = self.board.columns.first() or BoardColumn.objects.create(
            board=self.board, name="Todo", order=1
        )
        self.skill_category = SkillCategory.objects.create(name="General")
