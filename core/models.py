from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Model

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

    class Meta:
        unique_together = (
            "link",
            "content_type",
            "object_id",
        )
        verbose_name = "Ссылка"
        verbose_name_plural = "Ссылки"

    def __str__(self):
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

    class Meta:
        unique_together = (
            "user",
            "content_type",
            "object_id",
        )
        verbose_name = "Лайк"
        verbose_name_plural = "Лайки"

    def __str__(self):
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

    class Meta:
        unique_together = (
            "user",
            "content_type",
            "object_id",
        )
        verbose_name = "Просмотр"
        verbose_name_plural = "Просмотры"

    def __str__(self):
        return f"View<{self.user} - {self.content_object}>"


class Skill(models.Model):
    """
    Skill model
    """

    skill = models.CharField(max_length=256, null=False)

    class Meta:
        verbose_name = "Навык"
        verbose_name_plural = "Навыки"
        ordering = ["skill"]


class UserSkillTag(models.Model):
    """
    User skill tag model
    """

    skill_tag = models.CharField(max_length=256, null=False)
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name="tags",
    )

    class Meta:
        verbose_name = "Тег навыка"
        verbose_name_plural = "Теги навыков"
        ordering = ["skill_tag"]


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


class SpecializationCategory(models.Model):
    name = models.TextField()


class Specialization(models.Model):
    name = models.TextField()
    category = models.ForeignKey(
        SpecializationCategory, related_name="specializations", on_delete=models.CASCADE
    )
