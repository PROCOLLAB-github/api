from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

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
    is_competitive = models.BooleanField(
        default=False,
        verbose_name="Конкурсная программа",
        help_text="Если включено, проекты участников подлежат сдаче на проверку",
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
    registration_link = models.URLField(
        null=True,
        blank=True,
        verbose_name="Ссылка на регистрацию",
        help_text="Адрес страницы регистрации (например, на Tilda)",
    )
    max_project_rates = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=1,
        verbose_name="Максимальное количество оценок проектов",
        help_text="Ограничение на число экспертов, которые могут оценить один проект в программе",
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
    datetime_project_submission_ends = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата окончания подачи проектов",
        help_text="Если не указано, используется дата окончания регистрации",
    )
    datetime_evaluation_ends = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата окончания оценки проектов",
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

    def get_project_submission_deadline(self):
        """Возвращает дедлайн подачи проектов: отдельное поле или дата окончания регистрации."""
        return self.datetime_project_submission_ends or self.datetime_registration_ends

    def is_project_submission_open(self) -> bool:
        deadline = self.get_project_submission_deadline()
        return deadline is None or deadline >= timezone.now()


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


class PartnerProgramProject(models.Model):
    partner_program = models.ForeignKey(
        PartnerProgram, on_delete=models.CASCADE, related_name="program_projects"
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="program_links"
    )
    datetime_created = models.DateTimeField(auto_now_add=True)
    datetime_updated = models.DateTimeField(auto_now=True)
    submitted = models.BooleanField(default=False, verbose_name="Проект сдан")
    datetime_submitted = models.DateTimeField(
        null=True, blank=True, verbose_name="Дата сдачи проекта"
    )

    def can_edit(self, user: User) -> bool:
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser or user.is_staff:
            return True

        if self.project.leader_id == user.id:
            return not self.submitted

        return False

    class Meta:
        unique_together = ("partner_program", "project")
        verbose_name = "Проект участующий в программе"
        verbose_name_plural = "Проекеты участвующие в программах"

    def __str__(self):
        return f"{self.project} в программе {self.partner_program}"


class PartnerProgramField(models.Model):
    FIELD_TYPES = [
        ("text", "Однострочный текст"),
        ("textarea", "Многострочный текст"),
        ("checkbox", "Чекбокс"),
        ("select", "Выпадающий список"),
        ("radio", "Радио-кнопка"),
        ("file", "Файл"),
    ]

    partner_program = models.ForeignKey(
        PartnerProgram, on_delete=models.CASCADE, related_name="fields"
    )
    name = models.CharField(max_length=128, verbose_name="Служебное имя")
    label = models.CharField(max_length=256, verbose_name="Отображаемое название")
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    is_required = models.BooleanField(default=False)
    help_text = models.TextField(blank=True, null=True)
    show_filter = models.BooleanField(default=False)
    options = models.TextField(
        blank=True, null=True, help_text="Опции через | (для select/radio/checkbox)"
    )

    def __str__(self):
        return f"{self.partner_program.name} — {self.label} ({self.name})"

    class Meta:
        verbose_name = "Дополнительное поле программы"
        verbose_name_plural = "Дополнительные поля программ"
        unique_together = ("partner_program", "name")

    def get_options_list(self) -> list[str]:
        opts = self.options.split("|") if self.options else []
        return [opt.strip() for opt in opts if opt.strip()]


class PartnerProgramFieldValue(models.Model):
    program_project = models.ForeignKey(
        PartnerProgramProject, on_delete=models.CASCADE, related_name="field_values"
    )
    field = models.ForeignKey(
        PartnerProgramField, on_delete=models.CASCADE, related_name="values"
    )
    value_text = models.TextField(blank=False)

    class Meta:
        unique_together = ("program_project", "field")
        verbose_name = "Значение поля программы для проекта"
        verbose_name_plural = "Значения полей программы для проекта"
        indexes = [
            models.Index(fields=["program_project"]),
            models.Index(fields=["field"]),
        ]

    def __str__(self):
        return f"{self.field}: {self.value_text[:50]}"

    def get_value(self):
        return self.value_text

    def clean(self):
        if (
            self.program_project.partner_program.is_competitive
            and self.program_project.submitted
        ):
            raise ValidationError(
                "Нельзя изменять значения полей программы после сдачи проекта на проверку."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
