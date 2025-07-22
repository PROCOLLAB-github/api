from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models

from files.models import UserFile
from partner_programs.constants import get_default_data_schema
from projects.models import Project

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

    PROJECTS_AVAILABILITY_CHOISES = [
        ("all_users", "Всем пользователям"),
        ("experts_only", "Только экспертам"),
    ]

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
    managers = models.ManyToManyField(
        User,
        related_name="managed_partner_programs",
        blank=True,
        verbose_name="Менеджеры программы",
        help_text="Пользователи, имеющие право создавать и редактировать новости",
    )
    draft = models.BooleanField(blank=False, default=True)
    projects_availability = models.CharField(
        choices=PROJECTS_AVAILABILITY_CHOISES,
        max_length=25,
        default="all_users",
        verbose_name="Доступность к дочерним проектам",
    )
    datetime_registration_ends = models.DateTimeField(
        verbose_name="Дата окончания регистрации",
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
    datetime_updated = models.DateTimeField(
        verbose_name="Дата изменения", auto_now=True
    )

    def is_manager(self, user: User) -> bool:
        """
        Возвращает True, если пользователь — менеджер этой программы.
        """
        if not user or not user.is_authenticated:
            return False
        return self.managers.filter(pk=user.pk).exists()

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
        User,
        on_delete=models.SET_NULL,
        related_name="partner_program_profiles",
        null=True,
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        related_name="partner_program_profiles",
        null=True,
    )
    partner_program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="partner_program_profiles",
    )
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
        return f"PartnerProgramUserProfile<{self.pk}> - {self.user} {self.project} {self.partner_program}"


class PartnerProgramMaterial(models.Model):
    """
    Материал для программы: прямая ссылка или ссылка на прикреплённый файл.
    """

    program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="materials",
        verbose_name="Программа",
    )

    title = models.CharField(
        max_length=255,
        verbose_name="Название материала",
        help_text="Укажите текст для гиперссылки",
    )

    url = models.URLField(
        blank=True,
        null=True,
        verbose_name="Ссылка на материал",
        help_text="Укажите ссылку вручную или прикрепите файл",
    )

    file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="Файл",
        help_text="Если указан файл, ссылка берётся из него",
    )

    datetime_created = models.DateTimeField(auto_now_add=True)
    datetime_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Материал программы"
        verbose_name_plural = "Материалы программ"

    def clean(self):
        if self.file and not self.url:
            self.url = self.file.link

        if not self.file and not self.url:
            raise ValidationError("Необходимо указать либо файл, либо ссылку.")

        if self.file and self.url and self.url != self.file.link:
            raise ValidationError("Укажите либо файл, либо ссылку, но не оба сразу.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} для программы {self.program.name}"
