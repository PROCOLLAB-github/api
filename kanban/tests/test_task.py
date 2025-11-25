from datetime import date

from django.core.exceptions import ValidationError

from kanban.models import (
    Board,
    BoardColumn,
    BoardTag,
    Task,
    TaskTagLink,
    TaskSkillLink,
    TaskAttachment,
    TaskAssignee,
    TaskResult,
    TaskComment,
    TaskStatus,
)
from kanban.tests.base import BaseKanbanTestCase
from core.models import Skill
from files.models import UserFile
from projects.models import Collaborator, ProjectGoal, Project
from users.models import CustomUser


class TaskModelTests(BaseKanbanTestCase):
    def setUp(self):
        super().setUp()
        self.collaborator = CustomUser.objects.create(
            email="collab@example.com",
            first_name="Collab",
            last_name="User",
            password="pass1234",
            birthday=date(2000, 1, 1),
        )
        Collaborator.objects.create(project=self.project, user=self.collaborator)
        self.goal = ProjectGoal.objects.create(
            project=self.project,
            title="Goal",
            responsible=self.user,
        )
        self.task = Task.objects.create(
            column=self.column,
            name="Task name",
            responsible=self.collaborator,
            creator=self.user,
            goal=self.goal,
            start_date=date(2025, 1, 1),
            deadline=date(2025, 1, 10),
        )

    def test_column_must_match_board(self):
        another_board = Board.objects.create(project=self.project, name="Another")
        other_column = BoardColumn.objects.create(board=another_board, name="Doing", order=1)
        self.task.column = other_column
        with self.assertRaises(ValidationError):
            self.task.save()

    def test_goal_must_belong_to_same_project(self):
        other_project = Project.objects.create(name="Other", leader=self.user)
        foreign_goal = ProjectGoal.objects.create(
            project=other_project,
            title="Foreign",
            responsible=self.user,
        )
        self.task.goal = foreign_goal
        with self.assertRaises(ValidationError):
            self.task.save()

    def test_date_validation(self):
        self.task.start_date = date(2025, 2, 1)
        self.task.deadline = date(2025, 1, 1)
        with self.assertRaises(ValidationError):
            self.task.save()

    def test_responsible_must_be_project_member(self):
        outsider = CustomUser.objects.create(
            email="outsider@example.com",
            first_name="Out",
            last_name="Sider",
            password="pass1234",
            birthday=date(2000, 1, 1),
        )
        self.task.responsible = outsider
        with self.assertRaises(ValidationError):
            self.task.save()

    def test_status_and_completion(self):
        self.task.is_completed = True
        self.task.status = TaskStatus.DONE
        self.task.save()
        self.assertTrue(self.task.is_completed)


class TaskLinkTests(BaseKanbanTestCase):
    def setUp(self):
        super().setUp()
        self.collaborator = CustomUser.objects.create(
            email="collab@example.com",
            first_name="Collab",
            last_name="User",
            password="pass1234",
            birthday=date(2000, 1, 1),
        )
        Collaborator.objects.create(project=self.project, user=self.collaborator)
        self.task = Task.objects.create(
            column=self.column,
            name="Task",
            responsible=self.collaborator,
            creator=self.user,
        )

    def test_tag_limit(self):
        tags = [
            BoardTag.objects.create(board=self.board, name=f"Tag {i}", color="blue")
            for i in range(3)
        ]
        for tag in tags:
            TaskTagLink.objects.create(task=self.task, tag=tag)

        extra_tag = BoardTag.objects.create(board=self.board, name="Tag 4", color="blue")
        with self.assertRaises(ValidationError):
            TaskTagLink.objects.create(task=self.task, tag=extra_tag)

    def test_skill_limit(self):
        skills = [
            Skill.objects.create(name=f"Skill {i}", category=self.skill_category)
            for i in range(3)
        ]
        for skill in skills:
            TaskSkillLink.objects.create(task=self.task, skill=skill)

        extra_skill = Skill.objects.create(name="Skill 4", category=self.skill_category)
        with self.assertRaises(ValidationError):
            TaskSkillLink.objects.create(task=self.task, skill=extra_skill)

    def test_attachment_limit(self):
        files = [UserFile.objects.create(link=f"http://example.com/{i}") for i in range(3)]
        for file in files:
            TaskAttachment.objects.create(task=self.task, file=file)

        extra_file = UserFile.objects.create(link="http://example.com/4")
        with self.assertRaises(ValidationError):
            TaskAttachment.objects.create(task=self.task, file=extra_file)

    def test_assignee_limit_and_membership(self):
        users = []
        for i in range(7):
            user = CustomUser.objects.create(
                email=f"assignee{i}@example.com",
                first_name="Assignee",
                last_name=str(i),
                password="pass1234",
                birthday=date(2000, 1, 1),
            )
            Collaborator.objects.create(project=self.project, user=user)
            TaskAssignee.objects.create(task=self.task, user=user)
            users.append(user)

        outsider = CustomUser.objects.create(
            email="outsider@example.com",
            first_name="Out",
            last_name="Side",
            password="pass1234",
            birthday=date(2000, 1, 1),
        )
        with self.assertRaises(ValidationError):
            TaskAssignee.objects.create(task=self.task, user=outsider)

        another = CustomUser.objects.create(
            email="extra@example.com",
            first_name="Extra",
            last_name="User",
            password="pass1234",
            birthday=date(2000, 1, 1),
        )
        Collaborator.objects.create(project=self.project, user=another)
        with self.assertRaises(ValidationError):
            TaskAssignee.objects.create(task=self.task, user=another)


class TaskResultTests(BaseKanbanTestCase):
    def setUp(self):
        super().setUp()
        self.collaborator = CustomUser.objects.create(
            email="collab@example.com",
            first_name="Collab",
            last_name="User",
            password="pass1234",
            birthday=date(2000, 1, 1),
        )
        Collaborator.objects.create(project=self.project, user=self.collaborator)
        self.task = Task.objects.create(
            column=self.column,
            name="Task",
            responsible=self.collaborator,
            creator=self.user,
        )

    def test_result_creation_and_verification(self):
        file = UserFile.objects.create(link="http://example.com/result")
        result = TaskResult.objects.create(task=self.task, description="Done", result_file=file)
        self.assertFalse(result.is_verified)

        result.is_verified = True
        result.verified_by = self.user
        result.save()
        self.assertTrue(result.is_verified)


class TaskCommentTests(BaseKanbanTestCase):
    def setUp(self):
        super().setUp()
        self.collaborator = CustomUser.objects.create(
            email="collab@example.com",
            first_name="Collab",
            last_name="User",
            password="pass1234",
            birthday=date(2000, 1, 1),
        )
        Collaborator.objects.create(project=self.project, user=self.collaborator)
        self.task = Task.objects.create(
            column=self.column,
            name="Task",
            responsible=self.collaborator,
            creator=self.user,
        )

    def test_comment_creation_with_file(self):
        file = UserFile.objects.create(link="http://example.com/comment")
        comment = TaskComment.objects.create(
            task=self.task,
            author=self.user,
            text="Looks good",
            file=file,
        )
        self.assertEqual(comment.text, "Looks good")
        self.assertIsNotNone(comment.created_at)

    def test_comment_author_should_be_project_member(self):
        outsider = CustomUser.objects.create(
            email="outsider@example.com",
            first_name="Out",
            last_name="Side",
            password="pass1234",
            birthday=date(2000, 1, 1),
        )
        with self.assertRaises(ValidationError):
            TaskComment.objects.create(
                task=self.task,
                author=outsider,
                text="Hi",
            )
