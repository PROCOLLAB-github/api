import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.utils import timezone

from files.models import UserFile
from partner_programs.constants import get_default_data_schema
from projects.models import Project

User = get_user_model()


class LegalDocument(models.Model):
    TYPE_PRIVACY_POLICY = "privacy_policy"
    TYPE_PARTICIPANT_CONSENT = "participant_consent"
    TYPE_PARTICIPATION_TERMS = "participation_terms"
    TYPE_ORGANIZER_TERMS = "organizer_terms"

    TYPE_CHOICES = [
        (TYPE_PRIVACY_POLICY, "Privacy policy"),
        (TYPE_PARTICIPANT_CONSENT, "Participant personal data consent"),
        (TYPE_PARTICIPATION_TERMS, "Participation terms"),
        (TYPE_ORGANIZER_TERMS, "Organizer terms"),
    ]

    type = models.CharField(max_length=64, choices=TYPE_CHOICES, db_index=True)
    title = models.CharField(max_length=255)
    version = models.CharField(max_length=64)
    content_url = models.URLField(blank=True)
    content_html = models.TextField(blank=True)
    is_active = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Legal document"
        verbose_name_plural = "Legal documents"
        ordering = ("type", "-created_at", "-id")
        indexes = [
            models.Index(fields=("type", "is_active")),
        ]

    def __str__(self):
        return f"{self.type}:{self.version}"


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
    STATUS_DRAFT = "draft"
    STATUS_PENDING_MODERATION = "pending_moderation"
    STATUS_PUBLISHED = "published"
    STATUS_REJECTED = "rejected"
    STATUS_COMPLETED = "completed"
    STATUS_FROZEN = "frozen"
    STATUS_ARCHIVED = "archived"
    VERIFICATION_STATUS_NOT_REQUESTED = "not_requested"
    VERIFICATION_STATUS_PENDING = "pending"
    VERIFICATION_STATUS_VERIFIED = "verified"
    VERIFICATION_STATUS_REJECTED = "rejected"
    VERIFICATION_STATUS_REVOKED = "revoked"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PENDING_MODERATION, "Pending moderation"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FROZEN, "Frozen"),
        (STATUS_ARCHIVED, "Archived"),
    ]
    VERIFICATION_STATUS_CHOICES = [
        (VERIFICATION_STATUS_NOT_REQUESTED, "Not requested"),
        (VERIFICATION_STATUS_PENDING, "Pending"),
        (VERIFICATION_STATUS_VERIFIED, "Verified"),
        (VERIFICATION_STATUS_REJECTED, "Rejected"),
        (VERIFICATION_STATUS_REVOKED, "Revoked"),
    ]
    PARTICIPATION_FORMAT_INDIVIDUAL = "individual"
    PARTICIPATION_FORMAT_TEAM = "team"
    PARTICIPATION_FORMAT_CHOICES = [
        (PARTICIPATION_FORMAT_INDIVIDUAL, "Individual"),
        (PARTICIPATION_FORMAT_TEAM, "Team"),
    ]
    MODERATION_REQUIRED_SECTIONS = (
        "basic_info",
        "dates",
        "registration",
        "legal_terms",
    )
    READINESS_WEIGHTS = {
        "basic_info": 20,
        "dates": 15,
        "registration": 15,
        "legal_terms": 15,
        "materials": 10,
        "criteria_experts": 10,
        "visual_assets": 5,
        "verification": 5,
        "certificate_template": 5,
    }

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
    mobile_cover_image_address = models.URLField(
        null=True,
        blank=True,
        verbose_name="Mobile cover image URL",
        help_text=(
            "Optional mobile-optimized cover image. Falls back to "
            "cover_image_address when empty."
        ),
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
    draft = models.BooleanField(
        blank=False,
        default=True,
        verbose_name="[DEPRECATED] Draft",
        help_text="Legacy flag kept for backward compatibility; use status instead.",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
        verbose_name="Program status",
    )
    frozen_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Frozen at",
    )
    readiness = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Readiness checklist",
    )
    sent_reminders = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Sent readiness reminders",
    )
    company = models.ForeignKey(
        "projects.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="programs",
        verbose_name="Organizer company",
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default=VERIFICATION_STATUS_NOT_REQUESTED,
        db_index=True,
        verbose_name="Verification status",
    )
    is_private = models.BooleanField(
        default=False,
        verbose_name="Закрытый чемпионат",
        help_text="Доступ только по приглашению",
    )
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
    participation_format = models.CharField(
        max_length=20,
        choices=PARTICIPATION_FORMAT_CHOICES,
        default=PARTICIPATION_FORMAT_TEAM,
        verbose_name="Participation format",
        help_text="Team-size rule for a project linked to this championship.",
    )
    project_team_min_size = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=1,
        verbose_name="Minimum project team size",
    )
    project_team_max_size = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=None,
        verbose_name="Maximum project team size",
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
    datetime_updated = models.DateTimeField(verbose_name="Дата изменения", auto_now=True)

    def is_manager(self, user: User) -> bool:
        """
        Возвращает True, если пользователь — менеджер этой программы.
        """
        if not user or not user.is_authenticated:
            return False
        return self.managers.filter(pk=user.pk).exists()

    @property
    def is_published(self) -> bool:
        """Return true when the program should be visible on the public catalog."""
        return self.status == self.STATUS_PUBLISHED

    @property
    def is_editable_by_manager(self) -> bool:
        return self.status in (
            self.STATUS_DRAFT,
            self.STATUS_REJECTED,
            self.STATUS_PENDING_MODERATION,
            self.STATUS_PUBLISHED,
        )

    @property
    def can_be_submitted_to_moderation(self) -> bool:
        if self.status not in (self.STATUS_DRAFT, self.STATUS_REJECTED):
            return False
        readiness = self.calculate_readiness()
        return all(
            readiness.get(key) is True for key in self.MODERATION_REQUIRED_SECTIONS
        )

    def _related_exists(self, related_name: str) -> bool:
        try:
            return getattr(self, related_name).exists()
        except (AttributeError, ValueError):
            return False

    def _has_valid_registration_link(self) -> bool:
        link = (self.registration_link or "").strip()
        if not link:
            return False
        try:
            URLValidator()(link)
        except ValidationError:
            return False
        return True

    def _has_configured_registration_schema(self) -> bool:
        if self._related_exists("fields"):
            return True

        if not isinstance(self.data_schema, dict):
            return False
        if self.data_schema == get_default_data_schema():
            return False

        from partner_programs.privacy import iter_data_schema_fields

        allowed_types = {"text", "textarea", "checkbox", "select", "radio", "file"}
        for field_id, field in iter_data_schema_fields(self.data_schema):
            field_type = (
                field.get("type") or field.get("field_type") or field.get("fieldType")
            )
            label = field.get("label") or field.get("name") or field_id
            if (
                str(field_type or "").strip() in allowed_types
                and str(label or "").strip()
            ):
                return True
        return False

    def _has_registration_setup(self) -> bool:
        return (
            self._has_valid_registration_link()
            or self._has_configured_registration_schema()
        )

    def calculate_readiness(self) -> dict:
        try:
            certificate_template = getattr(self, "certificate_template", None)
        except AttributeError:
            certificate_template = None

        from project_rates.models import Criteria
        from partner_programs.privacy import (
            collect_privacy_blockers,
            has_privacy_blockers,
        )

        description = (self.description or "").strip()
        submission_deadline = self.datetime_project_submission_ends
        dates_valid = bool(
            self.datetime_started
            and self.datetime_registration_ends
            and submission_deadline
            and self.datetime_finished
            and self.datetime_started <= self.datetime_finished
            and self.datetime_registration_ends <= submission_deadline
            and submission_deadline <= self.datetime_finished
            and (
                not self.datetime_evaluation_ends
                or (
                    submission_deadline
                    <= self.datetime_evaluation_ends
                    <= self.datetime_finished
                )
            )
        )
        user_criteria = Criteria.objects.filter(partner_program=self).exclude(
            name="Комментарий"
        )
        criteria_weight_sum = sum(criteria.weight for criteria in user_criteria)
        criteria_experts_ready = (
            "not_applicable"
            if not self.is_competitive
            else bool(
                user_criteria.exists()
                and criteria_weight_sum == 100
                and self.experts.exists()
            )
        )

        return {
            "basic_info": bool(
                (self.name or "").strip()
                and description
                and len(description) >= 180
                and (self.city or "").strip()
            ),
            "dates": dates_valid,
            "registration": self._has_registration_setup(),
            "legal_terms": not has_privacy_blockers(collect_privacy_blockers(self)),
            "materials": self._related_exists("materials"),
            "criteria_experts": criteria_experts_ready,
            "visual_assets": bool(
                self.cover_image_address
                or self.mobile_cover_image_address
                or self.image_address
                or self.advertisement_image_address
            ),
            "certificate_template": certificate_template is not None,
            "verification": self.verification_status == self.VERIFICATION_STATUS_VERIFIED,
        }

    def get_readiness_percentage(self) -> int:
        readiness = self.calculate_readiness()
        percentage = sum(
            weight
            for key, weight in self.READINESS_WEIGHTS.items()
            if readiness.get(key) is True or readiness.get(key) == "not_applicable"
        )
        return max(0, min(100, int(percentage)))

    def get_operational_readiness_percentage(self) -> int:
        readiness = self.calculate_readiness()
        required_keys = ["materials"]
        if self.is_competitive:
            required_keys.append("criteria_experts")
        completed = sum(1 for key in required_keys if readiness.get(key) is True)
        return round(completed / len(required_keys) * 100)

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


class PartnerProgramVerificationRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    REJECTION_COMPANY_NOT_CONFIRMED = "company_not_confirmed"
    REJECTION_INSUFFICIENT_DOCUMENTS = "insufficient_documents"
    REJECTION_INVALID_DOCUMENTS = "invalid_documents"
    REJECTION_CONTACT_NOT_VERIFIED = "contact_not_verified"
    REJECTION_OTHER = "other"

    REJECTION_REASON_CHOICES = [
        (REJECTION_COMPANY_NOT_CONFIRMED, "Company data is not confirmed"),
        (REJECTION_INSUFFICIENT_DOCUMENTS, "Documents are insufficient"),
        (REJECTION_INVALID_DOCUMENTS, "Documents are invalid"),
        (REJECTION_CONTACT_NOT_VERIFIED, "Contact person is not verified"),
        (REJECTION_OTHER, "Other reason"),
    ]

    program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="verification_requests",
    )
    company = models.ForeignKey(
        "projects.Company",
        on_delete=models.PROTECT,
        related_name="program_verification_requests",
    )
    company_name = models.CharField(max_length=255, blank=True)
    inn = models.CharField(max_length=12, blank=True, db_index=True)
    legal_name = models.CharField(max_length=255, blank=True)
    ogrn = models.CharField(max_length=32, blank=True)
    website = models.URLField(blank=True)
    region = models.CharField(max_length=255, blank=True)
    initiator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="program_verification_requests",
    )
    contact_full_name = models.CharField(max_length=255)
    contact_position = models.CharField(max_length=255)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=64)
    company_role_description = models.TextField()
    documents = models.ManyToManyField(
        UserFile,
        related_name="program_verification_requests",
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decided_program_verification_requests",
    )
    admin_comment = models.TextField(blank=True)
    rejection_reason = models.CharField(
        max_length=40,
        choices=REJECTION_REASON_CHOICES,
        blank=True,
    )
    datetime_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Partner program verification request"
        verbose_name_plural = "Partner program verification requests"
        ordering = ["-submitted_at", "-id"]
        indexes = [
            models.Index(fields=["program", "-submitted_at"]),
            models.Index(fields=["status", "-submitted_at"]),
        ]

    def __str__(self):
        return f"VerificationRequest<{self.pk}> program={self.program_id}"


def default_invite_expires_at():
    return timezone.now() + timezone.timedelta(days=30)


class PartnerProgramInvite(models.Model):
    STATUS_PENDING = "pending"
    STATUS_USED = "used"
    STATUS_EXPIRED = "expired"
    STATUS_REVOKED = "revoked"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Ожидает использования"),
        (STATUS_USED, "Использовано"),
        (STATUS_EXPIRED, "Истёк срок"),
        (STATUS_REVOKED, "Отозвано"),
    ]

    program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="invites",
    )
    email = models.EmailField(db_index=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(default=default_invite_expires_at, db_index=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_program_invites",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_program_invites",
    )
    datetime_created = models.DateTimeField(auto_now_add=True)
    datetime_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Приглашение в чемпионат"
        verbose_name_plural = "Приглашения в чемпионаты"
        ordering = ["-datetime_created", "-id"]
        indexes = [
            models.Index(fields=["program", "status"]),
            models.Index(fields=["program", "-datetime_created"]),
        ]

    def __str__(self):
        return f"PartnerProgramInvite<{self.pk}> {self.email} program={self.program_id}"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()


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


class PartnerProgramLegalSettings(models.Model):
    program = models.OneToOneField(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="legal_settings",
    )
    participation_rules_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="program_legal_rule_settings",
    )
    participation_rules_link = models.URLField(blank=True)
    additional_terms_text = models.TextField(blank=True)
    organizer_terms_accepted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_program_organizer_terms",
    )
    organizer_terms_accepted_at = models.DateTimeField(null=True, blank=True)
    organizer_terms_version = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Program legal settings"
        verbose_name_plural = "Program legal settings"

    @property
    def terms_version(self) -> str:
        updated_value = self.updated_at or self.created_at or timezone.now()
        return f"program:{self.program_id}:{updated_value.isoformat()}"

    def __str__(self):
        return f"Legal settings for program {self.program_id}"


class PartnerProgramParticipantConsent(models.Model):
    program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="participant_consents",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="program_participant_consents",
    )
    consent_document_version = models.CharField(max_length=64)
    privacy_policy_version = models.CharField(max_length=64)
    participation_terms_version = models.CharField(max_length=128)
    consent_text_snapshot = models.TextField()
    accepted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)

    class Meta:
        verbose_name = "Participant championship consent"
        verbose_name_plural = "Participant championship consents"
        indexes = [
            models.Index(fields=("program", "user")),
            models.Index(fields=("accepted_at",)),
        ]

    def __str__(self):
        return f"Consent<{self.program_id}:{self.user_id}:{self.accepted_at}>"


class PersonalDataAccessLog(models.Model):
    ACTION_PARTICIPANT_LIST_VIEW = "participant_list_view"
    ACTION_PARTICIPANT_CONTACT_VIEW = "participant_contact_view"
    ACTION_PARTICIPANT_EXPORT_DOWNLOAD = "participant_export_download"

    ACTION_CHOICES = [
        (ACTION_PARTICIPANT_LIST_VIEW, "Participant list view"),
        (ACTION_PARTICIPANT_CONTACT_VIEW, "Participant contact view"),
        (ACTION_PARTICIPANT_EXPORT_DOWNLOAD, "Participant export download"),
    ]

    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="personal_data_access_logs",
    )
    program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.CASCADE,
        related_name="personal_data_access_logs",
    )
    action = models.CharField(max_length=64, choices=ACTION_CHOICES)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Personal data access log"
        verbose_name_plural = "Personal data access logs"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("program", "action", "created_at")),
            models.Index(fields=("actor", "created_at")),
        ]

    def save(self, *args, **kwargs):
        from partner_programs.privacy import sanitize_audit_metadata

        self.metadata = sanitize_audit_metadata(self.metadata)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.action} program={self.program_id} actor={self.actor_id}"


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
