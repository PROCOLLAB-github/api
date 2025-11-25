from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import Skill
from files.models import UserFile
from projects.models import Collaborator

User = get_user_model()


class BoardColor(models.TextChoices):
    BLUE = "blue", "Blue"
    GREEN = "green", "Green"
    ORANGE = "orange", "Orange"
    PURPLE = "purple", "Purple"
    RED = "red", "Red"


class BoardIcon(models.TextChoices):
    ROCKET = "rocket", "Rocket"
    TARGET = "target", "Target"
    BULB = "bulb", "Light Bulb"
    CHART = "chart", "Chart"
    NOTE = "note", "Note"


class Board(models.Model):
    MAX_PER_PROJECT = 5

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="kanban_boards",
    )
    name = models.CharField(max_length=150)
    color = models.CharField(
        max_length=32,
        choices=BoardColor.choices,
        default=BoardColor.BLUE,
    )
    icon = models.CharField(
        max_length=32,
        choices=BoardIcon.choices,
        default=BoardIcon.ROCKET,
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project_id", "id"]
        verbose_name = "Kanban board"
        verbose_name_plural = "Kanban boards"
        unique_together = ("project", "name")

    def __str__(self) -> str:
        return f"{self.project_id}:{self.name}"

    def clean(self):
        if (
            self.project_id
            and not self.pk
            and Board.objects.filter(project_id=self.project_id).count()
            >= self.MAX_PER_PROJECT
        ):
            raise ValidationError({"project": "Максимум пять досок на один проект."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class BoardColumn(models.Model):
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="columns",
    )
    name = models.CharField(max_length=150)
    order = models.PositiveIntegerField(default=0)
    tasks_count = models.PositiveIntegerField(
        default=0,
        editable=False,
        help_text="Количество задач в столбце.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "Board column"
        verbose_name_plural = "Board columns"
        constraints = [
            models.UniqueConstraint(
                fields=["board", "order"],
                name="unique_column_order_per_board",
            ),
            models.UniqueConstraint(
                fields=["board", "name"],
                name="unique_column_name_per_board",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.board}:{self.name}"

    def get_tasks_count(self) -> int:
        return self.tasks_count

    def delete(self, using=None, keep_parents=False):
        if self.board.columns.count() <= 1:
            raise ValidationError("Нельзя удалить последнюю колонку на доске.")
        return super().delete(using=using, keep_parents=keep_parents)


class BoardTag(models.Model):
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="tags",
    )
    name = models.CharField(max_length=80)
    color = models.CharField(
        max_length=32,
        choices=BoardColor.choices,
        default=BoardColor.BLUE,
    )

    class Meta:
        unique_together = ("board", "name")
        ordering = ["board_id", "name"]

    def __str__(self) -> str:
        return f"{self.board}:{self.name}"


class TaskType(models.TextChoices):
    ACTION = "action", "Action"
    MEETING = "meeting", "Meeting"
    CALL = "call", "Call"


class TaskStatus(models.TextChoices):
    TODO = "todo", "To do"
    IN_PROGRESS = "in_progress", "In progress"
    REVIEW = "review", "Review"
    DONE = "done", "Done"
    DECLINED = "declined", "Declined"


class Task(models.Model):
    MAX_TAGS = 3
    MAX_SKILLS = 3
    MAX_ASSIGNEES = 7
    MAX_FILES = 3

    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="tasks",
        editable=False,
    )
    column = models.ForeignKey(
        BoardColumn,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    task_type = models.CharField(
        max_length=32,
        choices=TaskType.choices,
        default=TaskType.ACTION,
    )
    priority = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(6)],
        default=3,
    )
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="responsible_tasks",
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
    )
    goal = models.ForeignKey(
        "projects.ProjectGoal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    is_completed = models.BooleanField(default=False)
    status = models.CharField(
        max_length=32,
        choices=TaskStatus.choices,
        default=TaskStatus.TODO,
    )
    points = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        default=1,
    )
    start_date = models.DateField(null=True, blank=True)
    deadline = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    tags = models.ManyToManyField(
        BoardTag,
        through="TaskTagLink",
        related_name="tasks",
        blank=True,
    )
    skills = models.ManyToManyField(
        Skill,
        through="TaskSkillLink",
        related_name="kanban_tasks",
        blank=True,
    )
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="TaskAssignee",
        related_name="assigned_tasks",
        blank=True,
    )
    files = models.ManyToManyField(
        UserFile,
        through="TaskAttachment",
        related_name="kanban_tasks",
        blank=True,
    )

    class Meta:
        ordering = ["column_id", "priority", "-created_at"]

    def __str__(self) -> str:
        return f"Task<{self.id}> {self.name}"

    @property
    def project(self):
        return self.board.project

    def clean(self):
        if self.column_id:
            column_board = self.column.board
            if self.board_id and column_board.id != self.board_id:
                raise ValidationError("Колонка принадлежит другой доске.")
            self.board = column_board

        if (
            self.goal_id
            and self.board_id
            and self.goal.project_id != self.board.project_id
        ):
            raise ValidationError("Цель относится к другому проекту.")

        if self.start_date and self.deadline and self.start_date > self.deadline:
            raise ValidationError("Дата начала не может быть позже дедлайна.")

        if self.responsible_id and not self._is_user_project_member(
            self.responsible_id
        ):
            raise ValidationError("Ответственный должен быть участником проекта.")

        if self.creator_id and not self._is_user_project_member(self.creator_id):
            raise ValidationError("Создатель должен быть участником проекта.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def _is_user_project_member(self, user_id: int) -> bool:
        project = self.board.project
        return (
            project.leader_id == user_id
            or Collaborator.objects.filter(
                project_id=project.id,
                user_id=user_id,
            ).exists()
        )


class TaskTagLink(models.Model):
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="task_tag_links"
    )
    tag = models.ForeignKey(
        BoardTag, on_delete=models.CASCADE, related_name="tag_links"
    )

    class Meta:
        unique_together = ("task", "tag")

    def clean(self):
        if self.tag.board_id != self.task.board_id:
            raise ValidationError("Тег принадлежит другой доске.")

        existing = (
            TaskTagLink.objects.filter(task=self.task).exclude(pk=self.pk).count()
        )
        if existing >= Task.MAX_TAGS:
            raise ValidationError("Нельзя привязать больше трёх тегов к задаче.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TaskSkillLink(models.Model):
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="task_skill_links"
    )
    skill = models.ForeignKey(
        Skill, on_delete=models.CASCADE, related_name="skill_links"
    )

    class Meta:
        unique_together = ("task", "skill")

    def clean(self):
        existing = (
            TaskSkillLink.objects.filter(task=self.task).exclude(pk=self.pk).count()
        )
        if existing >= Task.MAX_SKILLS:
            raise ValidationError("Нельзя указать больше трёх навыков.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TaskAttachment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    file = models.ForeignKey(
        UserFile, on_delete=models.CASCADE, related_name="task_attachments"
    )

    class Meta:
        unique_together = ("task", "file")

    def clean(self):
        existing = (
            TaskAttachment.objects.filter(task=self.task).exclude(pk=self.pk).count()
        )
        if existing >= Task.MAX_FILES:
            raise ValidationError("Можно прикрепить не больше трёх файлов.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TaskAssignee(models.Model):
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="assignee_links"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_assignees",
    )

    class Meta:
        unique_together = ("task", "user")

    def clean(self):
        project = self.task.board.project
        is_member = (
            project.leader_id == self.user_id
            or Collaborator.objects.filter(
                project_id=project.id,
                user_id=self.user_id,
            ).exists()
        )
        if not is_member:
            raise ValidationError("Исполнитель должен быть участником проекта.")

        existing = (
            TaskAssignee.objects.filter(task=self.task).exclude(pk=self.pk).count()
        )
        if existing >= Task.MAX_ASSIGNEES:
            raise ValidationError("Нельзя назначить больше семи исполнителей.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TaskResult(models.Model):
    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name="result")
    description = models.TextField()
    result_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_result_files",
    )
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_results",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Result for Task<{self.task_id}>"


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_comments",
    )
    text = models.TextField()
    file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_comment_files",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def clean(self):
        project = self.task.board.project
        if project.leader_id == self.author_id:
            return
        is_member = Collaborator.objects.filter(
            project_id=project.id,
            user_id=self.author_id,
        ).exists()
        if not is_member:
            raise ValidationError("Автор комментария должен быть участником проекта.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
