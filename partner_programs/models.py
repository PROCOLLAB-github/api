from django.contrib.auth import get_user_model
from django.db import models

from partner_programs.constants import get_default_data_schema

User = get_user_model()


class PartnerProgram(models.Model):
    """
    PartnerProgram model

    Attributes:
        name: A CharField name of the partner program.
        description: A TextField description of the partner program.
        image_address: A URLField image URL address.
        cover_image_address: A URLField cover image URL address.
        advertisement_image_address: A URLField advertisement image URL address.
        presentation_address: A URLField presentation URL address.
        users: A ManyToManyField of users.
        data_schema: A JSONField representing json schema of PartnerProgram fields.

        datetime_started: A DateTimeField indicating date of start.
        datetime_finished: A DateTimeField indicating date of finish.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    # links
    name = models.TextField(
        verbose_name="Название",
    )
    tag = models.TextField(
        verbose_name="Тег",
    )
    description = models.TextField(
        null=True,
        blank=True,
        verbose_name="Описание",
    )
    city = models.TextField(
        verbose_name="Город",
    )
    image_address = models.URLField(
        null=True,
        blank=True,
        verbose_name="Ссылка на аватар",
    )
    cover_image_address = models.URLField(
        null=True,
        blank=True,
        verbose_name="Ссылка на обложку",
    )
    advertisement_image_address = models.URLField(
        null=True,
        blank=True,
        verbose_name="Ссылка на обложку для рекламы",
    )
    presentation_address = models.URLField(
        null=True,
        blank=True,
        verbose_name="Ссылка на презентацию",
    )
    data_schema = models.JSONField(
        verbose_name="Схема данных в формате JSON",
        help_text="Ключи - имена полей, значения - тип поля ввода",
        default=get_default_data_schema,
    )

    users = models.ManyToManyField(
        User,
        related_name="partner_programs",
        blank=True,
        verbose_name="Участники программы",
        through="PartnerProgramUserProfile",
    )
    datetime_started = models.DateTimeField(
        verbose_name="Дата начала",
    )
    datetime_finished = models.DateTimeField(
        verbose_name="Дата окончания",
    )
    datetime_created = models.DateTimeField(
        verbose_name="Дата создания", auto_now_add=True
    )
    datetime_updated = models.DateTimeField(verbose_name="Дата изменения", auto_now=True)

    class Meta:
        verbose_name = "Программа"
        verbose_name_plural = "Программы"

    def __str__(self):
        return f"PartnerProgram<{self.pk}> - {self.name}"


class PartnerProgramUserProfile(models.Model):
    """
    PartnerProgramUserProfile model

    Attributes:
        user: A ForeignKey of the user.
        partner_program: A ForeignKey of the partner program.
        datetime_created: A DateTimeField indicating date of creation.
        datetime_updated: A DateTimeField indicating date of update.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="partner_program_profile"
    )
    partner_program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="partner_program_user_profile",
    )
    # views
    # likes
    # links
    # stats
    partner_program_data = models.JSONField()
    datetime_created = models.DateTimeField(auto_now_add=True)
    datetime_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Профиль"
        verbose_name_plural = "Профили"
        unique_together = (
            "user",
            "partner_program",
        )

    def __str__(self):
        return (
            f"PartnerProgramUserProfile<{self.pk}> - {self.user} {self.partner_program}"
        )
