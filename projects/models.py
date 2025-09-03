from typing import Optional

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import (
    MaxLengthValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.db.models import UniqueConstraint

from core.models import Like, View
from files.models import UserFile
from industries.models import Industry
from projects.managers import AchievementManager, CollaboratorManager, ProjectManager
from users.models import CustomUser

User = get_user_model()


class AbstractDefaultProjectImage(models.Model):
    """
    Абстрактная модель для хранения изображений проекта по умолчанию.
    """

    image = models.ForeignKey(
        UserFile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    datetime_created = models.DateTimeField(auto_now_add=True)
    datetime_updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @classmethod
    def get_random_file(cls) -> Optional[UserFile]:
        if not cls.objects.exists():
            return None
        obj = cls.objects.order_by("?").first()
        return obj.image if obj and obj.image else None

    @classmethod
    def get_random_file_link(cls) -> Optional[str]:
        file = cls.get_random_file()
        return file.link if file else None


class DefaultProjectCover(AbstractDefaultProjectImage):
    class Meta:
        verbose_name = "Обложка проекта"
        verbose_name_plural = "Обложки проектов"


class DefaultProjectAvatar(AbstractDefaultProjectImage):
    class Meta:
        verbose_name = "Аватарка проекта"
        verbose_name_plural = "Аватарки проектов"


class Project(models.Model):
    """
    Модель проекта.

    Атрибуты:
        name (CharField): Название проекта.
        description (TextField): Подробное описание проекта.
        region (CharField): Регион, в котором реализуется проект.
        hidden_score (PositiveSmallIntegerField): Скрытый рейтинг проекта,
            используется для внутренней сортировки.
        actuality (TextField): Актуальность проекта (почему он важен).
        target_audience (CharField): Описание целевой аудитории проекта.
        implementation_deadline (DateField): Общий срок реализации проекта (дата завершения).
        problem (TextField): Проблема, которую решает проект.
        trl (PositiveSmallIntegerField): Уровень технологической готовности (Technology Readiness Level) от 1 до 9.
        industry (ForeignKey): Ссылка на отрасль (модель Industry).
        presentation_address (URLField): Ссылка на презентацию проекта.
        image_address (URLField): Ссылка на изображение (аватар проекта).
        leader (ForeignKey): Руководитель проекта (пользователь).
        draft (BooleanField): Флаг, указывающий, является ли проект черновиком.
        is_company (BooleanField): Признак того, что проект представляет компанию.
        cover_image_address (URLField): Ссылка на обложку проекта.
        cover (ForeignKey): Файл-обложка проекта (устаревшее поле).
        subscribers (ManyToManyField): Подписчики проекта.
        datetime_created (DateTimeField): Дата создания проекта.
        datetime_updated (DateTimeField): Дата последнего изменения проекта.
    """

    name = models.CharField(max_length=256, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    region = models.CharField(max_length=256, null=True, blank=True)
    hidden_score = models.PositiveSmallIntegerField(default=100)
    actuality = models.TextField(
        blank=True,
        null=True,
        validators=[MaxLengthValidator(1000)],
        verbose_name="Актуальность",
        help_text="Почему проект важен (до 1000 симв.)",
    )
    target_audience = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name="Целевая аудитория",
        help_text="Описание целевой аудитории проекта (до 500 симв.)",
    )
    trl = models.PositiveSmallIntegerField(
        verbose_name="TRL",
        help_text="Technology Readiness Level (от 1 до 9)",
        validators=[MinValueValidator(1), MaxValueValidator(9)],
        null=True,
        blank=True,
    )
    implementation_deadline = models.DateField(
        verbose_name="Общий срок реализации проекта",
        help_text="Дата, до которой планируется реализовать проект",
        null=True,
        blank=True,
    )
    problem = models.TextField(
        blank=True,
        null=True,
        validators=[MaxLengthValidator(1000)],
        verbose_name="Проблема",
        help_text="Какую проблему решает проект (до 1000 симв.)",
    )

    industry = models.ForeignKey(
        Industry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects",
    )
    presentation_address = models.URLField(null=True, blank=True)
    image_address = models.URLField(null=True, blank=True)

    leader = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="leaders_projects",  # projects in which this user is the leader -
    )

    draft = models.BooleanField(blank=False, default=True)
    is_company = models.BooleanField(null=False, default=False)

    cover_image_address = models.URLField(
        null=True,
        blank=True,
        default=DefaultProjectCover.get_random_file_link,
        help_text="If left blank, will set a link to the image from the 'Обложки проектов'",
    )

    # TODO DELETE (deprecated field) after full migrate `cover_image_address`.
    cover = models.ForeignKey(
        UserFile,
        default=DefaultProjectCover.get_random_file,
        on_delete=models.SET_DEFAULT,
        related_name="project_cover",
        null=True,
        blank=True,
    )

    subscribers = models.ManyToManyField(
        User, verbose_name="Подписчики", related_name="subscribed_projects"
    )

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения", null=False, auto_now=True
    )

    objects = ProjectManager()

    def get_short_description(self) -> Optional[str]:
        return (
            self.description[:90] + ("..." if len(self.description) > 90 else "")
            if self.description
            else None
        )

    def get_collaborators_user_list(self) -> list[User]:
        return [collaborator.user for collaborator in self.collaborator_set.all()]

    def __str__(self):
        return f"Project<{self.id}> - {self.name}"

    def save(self, *args, **kwargs):
        """Set random cover and avatar images if not provided."""
        if not self.cover_image_address:
            self.cover_image_address = DefaultProjectCover.get_random_file_link()

        if not self.image_address:
            self.image_address = DefaultProjectAvatar.get_random_file_link()

        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-is_company", "-hidden_score", "-datetime_created"]
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"


class ProjectLink(models.Model):
    """
    Project link model

    Attributes:
        project: A ForeignKey referring to the Project model.
        link: A URLField link to the project.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="links",
    )
    link = models.URLField(null=False, blank=False)

    def __str__(self):
        return f"ProjectLink<{self.id}> - {self.project.name}"

    class Meta:
        verbose_name = "Ссылка проекта"
        verbose_name_plural = "Ссылки проектов"
        unique_together = ("project", "link")


class Achievement(models.Model):
    """
    Achievement model

     Attributes:
        title: A CharField title of the achievement.
        status: A CharField place or status of the achievement.
        project: A ForeignKey referring to the Project model.
    """

    title = models.CharField(max_length=256, null=False)
    status = models.CharField(max_length=256, null=False)

    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, related_name="achievements"
    )

    objects = AchievementManager()

    def __str__(self):
        return f"Achievement<{self.id}>"

    class Meta:
        verbose_name = "Достижение"
        verbose_name_plural = "Достижения"


class Collaborator(models.Model):
    """
    Project collaborator model

    Attributes:
        user: A ForeignKey referencing the user who is collaborating in the project.
        project: A ForeignKey referencing the project the user is collaborating in.
        role: A CharField meaning the role the user is fulfilling in the project.
        specialization: A CharField indicating the user's specialization within the project.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    user = models.ForeignKey(
        CustomUser,
        models.CASCADE,
        verbose_name="Пользователь",
        related_name="collaborations",
    )
    project = models.ForeignKey(Project, models.CASCADE, verbose_name="Проект")
    role = models.CharField("Роль", max_length=1024, blank=True, null=True)
    specialization = models.CharField(
        "Специализация",
        max_length=100,
        blank=True,
        null=True,
        default=None,
        help_text="Направления работы участника в рамках проекта",
    )

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", null=False, auto_now_add=True
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения", null=False, auto_now=True
    )

    objects = CollaboratorManager()

    class Meta:
        verbose_name = "Коллаборатор"
        verbose_name_plural = "Коллабораторы"
        constraints = [
            UniqueConstraint(
                fields=[
                    "project",
                    "user",
                ],
                name="unique_collaborator",
            )
        ]


class ProjectNews(models.Model):
    """
    Project news model
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="news",
    )
    text = models.TextField(
        null=False,
        blank=False,
    )
    # todo: remove files unused files
    files = models.ManyToManyField(UserFile, related_name="projects_news", blank=True)

    views = GenericRelation(
        View,
        related_query_name="project_views",
    )
    likes = GenericRelation(
        Like,
        related_query_name="project_news",
    )

    datetime_created = models.DateTimeField(
        verbose_name="Дата создания",
        null=False,
        auto_now_add=True,
    )
    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения",
        null=False,
        auto_now=True,
    )

    class Meta:
        verbose_name = "Новость проекта"
        verbose_name_plural = "Новости проекта"
        ordering = ["-datetime_created"]
