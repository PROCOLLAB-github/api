from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Model
from django_stubs_ext.db.models import TypedModelMeta

User = get_user_model()


class Link(Model):
    """
    Generic Link model based on contenttype
    """

    link = models.URLField(
        verbose_name="Ссылка",
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="links",
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta(TypedModelMeta):
        unique_together = (
            "link",
            "content_type",
            "object_id",
        )
        verbose_name = "Ссылка"
        verbose_name_plural = "Ссылки"

    def __str__(self) -> str:
        return f"Link for {self.content_object} - {self.link}"


class Like(Model):
    """
    Generic Like model based on contenttype
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="likes",
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="likes",
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta(TypedModelMeta):
        unique_together = (
            "user",
            "content_type",
            "object_id",
        )
        verbose_name = "Лайк"
        verbose_name_plural = "Лайки"

    def __str__(self) -> str:
        return f"Like<{self.user} - {self.content_object}>"


class View(Model):
    """
    Generic View model based on contenttype

    Indicates if user has viewed the object

    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="views",
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="views",
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta(TypedModelMeta):
        unique_together = (
            "user",
            "content_type",
            "object_id",
        )
        verbose_name = "Просмотр"
        verbose_name_plural = "Просмотры"

    def __str__(self) -> str:
        return f"View<{self.user} - {self.content_object}>"


class SkillCategory(models.Model):
    """
    Skill category model
    """

    name = models.CharField(max_length=256, null=False)

    def __str__(self) -> str:
        return self.name

    class Meta(TypedModelMeta):
        verbose_name = "Категория навыка"
        verbose_name_plural = "Категории навыков"
        ordering = ["name"]


class Skill(models.Model):
    """
    Skill model
    """

    name = models.CharField(max_length=256, null=False)
    category = models.ForeignKey(
        SkillCategory,
        on_delete=models.CASCADE,
        related_name="skills",
    )

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"Skill<name={self.name},id={self.id}>"

    class Meta(TypedModelMeta):
        verbose_name = "Навык"
        verbose_name_plural = "Навыки"
        ordering = ["id", "category", "name"]


class SkillToObject(models.Model):
    """
    Skill model for skill_2_user/vacancy/project/etc relation
    """

    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name="skills",
    )

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="skills",
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta(TypedModelMeta):
        verbose_name = "Ссылка на навык"
        verbose_name_plural = "Ссылки на навыки"

    def __str__(self):
        try:
            return f"{self.skill.name} - {self.content_object}"
        # Possible contingencies with attributes.
        except Exception:
            pass
        return super().__str__()


class SpecializationCategory(models.Model):
    name = models.TextField()

    def __str__(self) -> str:
        return self.name

    class Meta(TypedModelMeta):
        verbose_name = "Категория специализации"
        verbose_name_plural = "Категории специализаций"


class Specialization(models.Model):
    name = models.TextField()
    category = models.ForeignKey(
        SpecializationCategory, related_name="specializations", on_delete=models.CASCADE
    )

    def __str__(self) -> str:
        return self.name

    class Meta(TypedModelMeta):
        verbose_name = "Специализация"
        verbose_name_plural = "Специализации"


class SpecializationToObject(models.Model):
    specialization = models.ForeignKey(
        Specialization, related_name="specializations", on_delete=models.CASCADE
    )

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="specializations",
    )
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
