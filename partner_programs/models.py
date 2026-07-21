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

    PARTICIPATION_FORMAT_INDIVIDUAL_ONLY = "individual_only"
    PARTICIPATION_FORMAT_TEAM_ONLY = "team_only"
    PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM = "individual_or_team"

    PARTICIPATION_FORMAT_CHOICES = (
        (PARTICIPATION_FORMAT_INDIVIDUAL_ONLY, "Только индивидуально"),
        (PARTICIPATION_FORMAT_TEAM_ONLY, "Только в команде"),
        (PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM, "Индивидуально или в команде"),
    )

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
    is_distributed_evaluation = models.BooleanField(
        default=False,
        verbose_name="Распределенное оценивание",
        help_text=(
            "Если включено, проекты для оценки доступны только назначенным экспертам"
        ),
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
    publish_projects_after_finish = models.BooleanField(
        default=False,
        verbose_name="Публиковать проекты после окончания программы",
        help_text="Если включено, проекты участников станут публичными после завершения программы",
    )
    # До появления выбора формата весь существующий flow остается индивидуальным.
    participation_format = models.CharField(
        max_length=24,
        choices=PARTICIPATION_FORMAT_CHOICES,
        default=PARTICIPATION_FORMAT_INDIVIDUAL_ONLY,
        verbose_name="Разрешенный формат участия",
    )
    # Будущий service считает accepted-участников вместе с капитаном.
    team_min_size = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Минимальный размер команды",
        help_text="Количество принятых участников с учетом капитана",
    )
    team_max_size = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Максимальный размер команды",
        help_text="Количество принятых участников с учетом капитана",
    )
    datetime_registration_ends = models.DateTimeField(
        verbose_name="Дата окончания регистрации",
    )
    datetime_application_ends = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата окончания подачи заявок",
        help_text="Отдельный дедлайн Application; другие дедлайны не используются как fallback",
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

    def clean(self):
        """Проверяет согласованность формата участия и размеров команды."""
        super().clean()
        errors = {}

        if self.participation_format == self.PARTICIPATION_FORMAT_INDIVIDUAL_ONLY:
            if self.team_min_size is not None:
                errors["team_min_size"] = (
                    "Для индивидуального формата минимальный размер команды не задается."
                )
            if self.team_max_size is not None:
                errors["team_max_size"] = (
                    "Для индивидуального формата максимальный размер команды не задается."
                )
        elif self.participation_format in {
            self.PARTICIPATION_FORMAT_TEAM_ONLY,
            self.PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM,
        }:
            if self.team_min_size is None:
                errors["team_min_size"] = (
                    "Для командного формата укажите минимальный размер команды."
                )
            elif self.team_min_size < 2:
                errors["team_min_size"] = (
                    "Минимальный размер команды должен быть не меньше двух."
                )

            if self.team_max_size is None:
                errors["team_max_size"] = (
                    "Для командного формата укажите максимальный размер команды."
                )
            elif self.team_max_size < 2:
                errors["team_max_size"] = (
                    "Максимальный размер команды должен быть не меньше двух."
                )
            elif (
                self.team_min_size is not None
                and self.team_max_size < self.team_min_size
            ):
                errors["team_max_size"] = (
                    "Максимальный размер команды не может быть меньше минимального."
                )

        if errors:
            raise ValidationError(errors)

    def allows_participation_mode(self, mode: str) -> bool:
        """Возвращает, разрешен ли выбранный финальный формат заявки."""
        allowed_modes = {
            self.PARTICIPATION_FORMAT_INDIVIDUAL_ONLY: {
                Application.PARTICIPATION_MODE_INDIVIDUAL
            },
            self.PARTICIPATION_FORMAT_TEAM_ONLY: {
                Application.PARTICIPATION_MODE_TEAM
            },
            self.PARTICIPATION_FORMAT_INDIVIDUAL_OR_TEAM: {
                Application.PARTICIPATION_MODE_INDIVIDUAL,
                Application.PARTICIPATION_MODE_TEAM,
            },
        }
        return mode in allowed_modes.get(self.participation_format, set())

    def is_application_deadline_passed(self, at=None) -> bool:
        """Проверяет отдельный дедлайн Application без fallback на legacy-поля."""
        if self.datetime_application_ends is None:
            return False
        moment = at if at is not None else timezone.now()
        return moment > self.datetime_application_ends

    class Meta:
        verbose_name = "Программа"
        verbose_name_plural = "Программы"
        # Constraints защищают policy одной программы. Фактический состав Team
        # требует проверки связанных строк в будущем транзакционном service.
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(team_min_size__isnull=True)
                    | models.Q(team_min_size__gte=2)
                ),
                name="program_team_min_gte_2_or_null",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(team_max_size__isnull=True)
                    | models.Q(team_max_size__gte=2)
                ),
                name="program_team_max_gte_2_or_null",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(team_min_size__isnull=True)
                    | models.Q(team_max_size__isnull=True)
                    | models.Q(team_max_size__gte=models.F("team_min_size"))
                ),
                name="program_team_max_gte_min",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(
                        participation_format="individual_only",
                        team_min_size__isnull=True,
                        team_max_size__isnull=True,
                    )
                    | models.Q(
                        participation_format__in=(
                            "team_only",
                            "individual_or_team",
                        ),
                        team_min_size__isnull=False,
                        team_max_size__isnull=False,
                    )
                ),
                name="program_team_sizes_match_format",
            ),
        ]

    def __str__(self):
        return f"PartnerProgram<{self.pk}> - {self.name}"

    def get_project_submission_deadline(self):
        """Возвращает дедлайн подачи проектов: отдельное поле или дата окончания регистрации."""
        return self.datetime_project_submission_ends or self.datetime_registration_ends

    def is_project_submission_open(self) -> bool:
        deadline = self.get_project_submission_deadline()
        return deadline is None or deadline >= timezone.now()


class Application(models.Model):
    """Заявка пользователя на участие в партнерской программе."""

    PARTICIPATION_MODE_UNDECIDED = "undecided"
    PARTICIPATION_MODE_INDIVIDUAL = "individual"
    PARTICIPATION_MODE_TEAM = "team"

    PARTICIPATION_MODE_CHOICES = (
        (PARTICIPATION_MODE_UNDECIDED, "Не определен"),
        (PARTICIPATION_MODE_INDIVIDUAL, "Индивидуально"),
        (PARTICIPATION_MODE_TEAM, "В команде"),
    )

    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_CANCELLED = "cancelled"

    ACTIVE_STATUSES = (
        STATUS_DRAFT,
        STATUS_SUBMITTED,
        STATUS_APPROVED,
    )

    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_WITHDRAWN, "Withdrawn"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="program_applications",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_program_applications",
    )
    # Временный default сохраняет совместимость с API и frontend, которые пока
    # не передают формат участия. `undecided` станет default вместе с wizard.
    participation_mode = models.CharField(
        max_length=16,
        choices=PARTICIPATION_MODE_CHOICES,
        default=PARTICIPATION_MODE_INDIVIDUAL,
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    form_data = models.JSONField(default=dict, blank=True)
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        related_name="applications",
        null=True,
        blank=True,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        errors = {}

        if not self.user_id:
            errors["user"] = (
                "User is required as the application owner and team captain in MVP."
            )

        if self.user_id and self.program_id and self.status in self.ACTIVE_STATUSES:
            duplicate_qs = Application.objects.filter(
                user_id=self.user_id,
                program_id=self.program_id,
                status__in=self.ACTIVE_STATUSES,
            )
            if self.pk:
                duplicate_qs = duplicate_qs.exclude(pk=self.pk)
            if duplicate_qs.exists():
                errors["user"] = (
                    "User already has an active application for this program."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Application"
        verbose_name_plural = "Applications"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "program"],
                condition=models.Q(
                    user__isnull=False,
                    status__in=("draft", "submitted", "approved"),
                ),
                name="uniq_active_application_user_program",
            ),
        ]

    def __str__(self):
        return (
            f"Application<{self.pk}> "
            f"user={self.user_id} program={self.program_id} status={self.status}"
        )


class Team(models.Model):
    """Команда конкретной заявки, независимая от состава связанного Project."""

    application = models.OneToOneField(
        Application,
        on_delete=models.CASCADE,
        related_name="team",
    )
    name = models.CharField(max_length=255, blank=True, default="")
    captain = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="captained_application_teams",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        """Проверяет формат заявки и единого владельца командного MVP."""
        super().clean()

        errors = {}
        if self.application_id:
            application = self.application
            if application.participation_mode != Application.PARTICIPATION_MODE_TEAM:
                errors["application"] = (
                    "Команду можно создать только для заявки с командным форматом."
                )
            if self.captain_id and self.captain_id != application.user_id:
                errors["captain"] = (
                    "Капитан команды должен совпадать с владельцем заявки."
                )

        # Полный invariant намеренно не требует captain TeamMember: при первом
        # сохранении Team связанная запись участника еще не может существовать.
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Команда заявки"
        verbose_name_plural = "Команды заявок"

    def __str__(self):
        return f"Team<{self.pk}> application={self.application_id} name={self.name}"


class TeamMember(models.Model):
    """Членство пользователя в команде конкретной заявки."""

    ROLE_CAPTAIN = "captain"
    ROLE_MEMBER = "member"

    ROLE_CHOICES = (
        (ROLE_CAPTAIN, "Капитан"),
        (ROLE_MEMBER, "Участник"),
    )

    STATUS_INVITED = "invited"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_REMOVED = "removed"
    STATUS_LEFT = "left"

    STATUS_CHOICES = (
        (STATUS_INVITED, "Приглашен"),
        (STATUS_ACCEPTED, "Принят"),
        (STATUS_DECLINED, "Отклонил приглашение"),
        (STATUS_REMOVED, "Исключен"),
        (STATUS_LEFT, "Покинул команду"),
    )

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="members",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="application_team_memberships",
    )
    role = models.CharField(
        max_length=16,
        choices=ROLE_CHOICES,
        default=ROLE_MEMBER,
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_INVITED,
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="invited_application_team_members",
        null=True,
        blank=True,
    )
    joined_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        """Проверяет роль капитана и фиксирует первое принятие в команду."""
        super().clean()

        errors = {}
        if self.role == self.ROLE_CAPTAIN:
            if self.status != self.STATUS_ACCEPTED:
                errors["status"] = "Капитан должен быть принятым участником команды."
            if self.team_id and self.user_id != self.team.captain_id:
                errors["user"] = "Капитан-участник должен совпадать с капитаном команды."

        if self.status == self.STATUS_ACCEPTED and self.joined_at is None:
            self.joined_at = timezone.now()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        joined_at_was_missing = self.joined_at is None
        self.full_clean()
        if (
            joined_at_was_missing
            and self.joined_at is not None
            and kwargs.get("update_fields") is not None
        ):
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"joined_at"}
        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Участник команды заявки"
        verbose_name_plural = "Участники команд заявок"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user"],
                name="uniq_team_member_user",
            ),
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(
                    role="captain",
                    status="accepted",
                ),
                name="uniq_accepted_captain_team",
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(role="captain")
                    | models.Q(status="accepted")
                ),
                name="captain_team_member_is_accepted",
            ),
        ]
        # Конфликт участий между командами и индивидуальными заявками проходит
        # через несколько таблиц и требует отдельного транзакционного service.

    def __str__(self):
        return (
            f"TeamMember<{self.pk}> team={self.team_id} "
            f"user={self.user_id} role={self.role} status={self.status}"
        )


class Submission(models.Model):
    """Versioned solution submitted for an application and program stage."""

    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_RETURNED = "returned"
    STATUS_FINAL = "final"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_RETURNED, "Returned"),
        (STATUS_FINAL, "Final"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    EDITABLE_STATUSES = (
        STATUS_DRAFT,
        STATUS_RETURNED,
    )

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="submissions",
    )
    program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="submissions",
    )
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="program_submissions",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    form_data = models.JSONField(default=dict, blank=True)
    links = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    version = models.PositiveIntegerField(default=1)
    stage_key = models.CharField(max_length=128, default="main")
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        errors = {}
        if self.application_id:
            application = self.application

            if self.program_id and self.program_id != application.program_id:
                errors["program"] = "Program must match the application's program."

            allowed_submitter_ids = {
                application.user_id,
                application.created_by_id,
            }
            allowed_submitter_ids.discard(None)
            if (
                self.submitted_by_id
                and self.submitted_by_id not in allowed_submitter_ids
                and not (
                    self.submitted_by.is_staff or self.submitted_by.is_superuser
                )
            ):
                errors["submitted_by"] = (
                    "Submitted by must match the application user or creator."
                )

            if self._state.adding and application.status in (
                Application.STATUS_WITHDRAWN,
                Application.STATUS_REJECTED,
                Application.STATUS_CANCELLED,
            ):
                errors["application"] = (
                    "Submissions cannot be created for inactive applications."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def is_draft(self):
        return self.status == self.STATUS_DRAFT

    @property
    def is_submitted(self):
        return self.status == self.STATUS_SUBMITTED

    @property
    def is_final(self):
        return self.status == self.STATUS_FINAL

    @property
    def can_edit(self):
        return self.status in self.EDITABLE_STATUSES

    @property
    def can_submit(self):
        return self.status in self.EDITABLE_STATUSES

    class Meta:
        verbose_name = "Submission"
        verbose_name_plural = "Submissions"
        constraints = [
            models.UniqueConstraint(
                fields=["application", "stage_key", "version"],
                name="uniq_submission_application_stage_version",
            ),
            models.CheckConstraint(
                check=models.Q(version__gte=1),
                name="submission_version_gte_1",
            ),
        ]

    def __str__(self):
        return (
            f"Submission<{self.pk}> application={self.application_id} "
            f"stage={self.stage_key} version={self.version} status={self.status}"
        )


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
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"

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
