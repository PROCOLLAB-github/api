from functools import partial

from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.db.models import QuerySet
from django.utils import timezone
from django_stubs_ext.db.models import TypedModelMeta

from users import constants
from users.managers import (
    CustomUserManager,
    LikesOnProjectManager,
    UserAchievementManager,
)
from users.utils import normalize_user_phone
from users.validators import (
    user_birthday_validator,
    user_experience_years_range_validator,
    user_name_validator,
    user_phone_number_validation,
)


def get_default_user_type():
    return CustomUser.MEMBER


class CustomUser(AbstractUser):
    """
    CustomUser model

    This model is used to store the user common information.

    Attributes:
        email: CharField instance of user's email.
        first_name: CharField instance of the user first name.
        last_name: CharField instance of the user last name.
        password: CharField instance of the user password.
        is_active: Boolean indicating if user confirmed email.
        user_type: PositiveSmallIntegerField indicating the user's type
                   according to VERBOSE_USER_TYPES.
        patronymic: CharField instance of the user patronymic.
        avatar: URLField instance of the user's avatar url.
        birthday: DateField instance of the user's birthday.
        about_me: TextField instance contains information about the user.
        status: CharField instance notifies about the user's status.
        region: CharField instance the user's name region.
        city: CharField instance the user's name city.
        speciality: CharField instance the user's specialty.
        datetime_updated: A DateTimeField indicating date of update.
        datetime_created: A DateTimeField indicating date of creation.
        dataset_migration_applied: A BooleanField indicating based on
                    the `v2_speciality` and `skills`.
    """

    ADMIN = constants.ADMIN
    MEMBER = constants.MEMBER
    MENTOR = constants.MENTOR
    EXPERT = constants.EXPERT
    INVESTOR = constants.INVESTOR

    username = None
    email = models.EmailField(
        unique=True,
        error_messages={
            "unique": "Пользователь с таким email уже существует",
        },
    )
    first_name = models.CharField(
        max_length=255, validators=[partial(user_name_validator, field_name="Имя")]
    )
    last_name = models.CharField(
        max_length=255, validators=[partial(user_name_validator, field_name="Фамилия")]
    )
    password = models.CharField(max_length=255)
    is_active = models.BooleanField(default=False, editable=False)
    user_type = models.PositiveSmallIntegerField(
        choices=constants.VERBOSE_USER_TYPES,
        default=get_default_user_type,
    )
    ordering_score = models.PositiveIntegerField(
        default=0,
        editable=False,
    )
    patronymic = models.CharField(
        max_length=255,
        validators=[partial(user_name_validator, field_name="Отчество")],
        null=True,
        blank=True,
    )
    # TODO need to be removed in future `key_skills` -> `skills`.
    key_skills = models.CharField(
        max_length=512,
        null=True,
        blank=True,
        help_text="Устаревшее поле -> skills",
    )
    skills = GenericRelation(
        "core.SkillToObject",
        related_query_name="users",
    )
    avatar = models.URLField(
        null=True,
        blank=True,
        validators=[URLValidator(message="Введите корректный URL")],
    )
    birthday = models.DateField(
        validators=[user_birthday_validator],
    )
    about_me = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=255, null=True, blank=True)
    region = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=255, null=True, blank=True)
    phone_number = models.CharField(
        max_length=20,
        validators=[user_phone_number_validation],
        null=True,
        blank=True,
        verbose_name="Номер телефона",
        help_text="Пример: +7 XXX XX-XX-XX | +7XXXXXXXXX | +7 (XXX) XX-XX-XX",
    )
    v2_speciality = models.ForeignKey(
        on_delete=models.SET_NULL,
        null=True,
        related_name="users",
        to="core.Specialization",
    )
    # TODO need to be removed in future `speciality` -> `v2_speciality`.
    speciality = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Устаревшее поле -> v2_speciality",
    )
    onboarding_stage = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        editable=False,
        default=constants.OnboardingStage.intro.value,
        verbose_name="Стадия онбординга",
        help_text="0, 1, 2 - номера стадий онбординга, null(пустое) - онбординг пройден",
    )
    verification_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Дата верификации",
    )
    datetime_updated = models.DateTimeField(auto_now=True)
    datetime_created = models.DateTimeField(auto_now_add=True)
    # TODO need to be removed in future.
    dataset_migration_applied = models.BooleanField(
        null=True,
        blank=True,
        default=False,
        verbose_name="Временная мера для переноса навыка",
        help_text="Yes если оба поля `v2_speciality` и `skills` есть, No если поля не перенеслись",
    )
    is_mospolytech_student = models.BooleanField(
        default=False,
        verbose_name="Студент Московского Политеха",
        help_text="Флаг, указывающий, является ли пользователь студентом МосПолитеха",
    )
    study_group = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        verbose_name="Учебная группа",
        help_text="Краткое обозначение учебной группы (до 10 символов)",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    @property
    def skills_count(self):
        return self.skills.count()

    def get_skills(self):
        return [sto.skill for sto in self.skills.all()]

    def calculate_ordering_score(self) -> int:
        """
        Calculate ordering score of the user, e.g. how full their profile is.

        Returns:
            int: ordering score of the user.
        """
        score = 0
        if self.avatar:
            score += 10
        if self.skills_count > 0:
            score += 7
        if self.about_me:
            score += 6
        if self.region:
            score += 4
        if self.city:
            score += 4
        # TODO need to be removed in future.
        if self.education.all().exists():
            score += 6
        if self.speciality:
            score += 7
        return score

    def get_project_chats(self) -> QuerySet:
        from chats.models import ProjectChat

        user_project_ids = self.collaborations.all().values_list(
            "project_id", flat=True
        )
        return ProjectChat.objects.filter(project__in=user_project_ids)

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def get_user_age(self) -> int:
        if self.birthday is None:
            return None
        today = timezone.now()
        birthday = self.birthday
        return (
            today.year
            - birthday.year
            - ((today.month, today.day) < (birthday.month, birthday.day))
        )

    def __str__(self) -> str:
        return f"User<{self.id}> - {self.first_name} {self.last_name}"

    def save(self, *args, **kwargs):
        if self.phone_number:
            self.phone_number = normalize_user_phone(self.phone_number)
        super().save(*args, **kwargs)

    class Meta(TypedModelMeta):
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        # order by count of fields inputted, like avatar, skills, about_me, etc.
        # first show users with all fields inputted, then with 1 field inputted, etc.
        ordering = ["-ordering_score", "id"]


class UserAchievement(models.Model):
    """
    UserAchievement model

     Attributes:
        title: A CharField title of the achievement.
        status: A CharField place or status of the achievement.
        user: A ForeignKey referring to the CustomUser model.
    """

    title = models.CharField(max_length=256)
    status = models.CharField(max_length=256)

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="achievements",
    )

    objects = UserAchievementManager()

    def __str__(self):
        return f"UserAchievement<{self.id}>"

    class Meta(TypedModelMeta):
        verbose_name = "Достижение"
        verbose_name_plural = "Достижения"


class AbstractUserWithRole(models.Model):
    """
    AbstractUserWithRole abstract model

    This model adds additional role field to the user model.

    Attributes:
        first_additional_role: PositiveSmallIntegerField indicating the user's additional role
                         according to VERBOSE_ROLE_TYPES.
        second_additional_role: the same as first one.
    """

    first_additional_role = models.PositiveSmallIntegerField(
        choices=constants.VERBOSE_ROLE_TYPES,
        null=True,
    )
    second_additional_role = models.PositiveSmallIntegerField(
        choices=constants.VERBOSE_ROLE_TYPES,
        null=True,
    )

    class Meta(TypedModelMeta):
        abstract = True


class LikesOnProject(models.Model):
    """
    LikesOnProject model

    This model is used to store the user's likes on projects.

    Attributes:
        user: ForeignKey instance of user.
        project: ForeignKey instance of project.
    """

    is_liked = models.BooleanField(default=True)

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="likes_on_projects",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="likes",
    )

    objects = LikesOnProjectManager()

    def toggle_like(self):
        self.is_liked = not self.is_liked
        self.save()

    def __str__(self):
        return f"LikesOnProject<{self.id}>"

    class Meta(TypedModelMeta):
        verbose_name = "Лайк на проект"
        verbose_name_plural = "Лайки на проекты"
        unique_together = ("user", "project")


class Member(models.Model):
    """
    Member model

    Represents the CustomUser with the MEMBER user type.

    Attributes:
        user: ForeignKey instance of the CustomUser model.
        useful_to_project: TextField instance indicates actions useful
                           for the development and maintenance of the project.
    """

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="member"
    )

    useful_to_project = models.TextField(blank=True)

    class Meta(TypedModelMeta):
        verbose_name = "Участник"
        verbose_name_plural = "Участники"

    def __str__(self):
        return f"Member<{self.id}> - {self.user.first_name} {self.user.last_name}"


class Mentor(AbstractUserWithRole):
    """
    Mentor model

    Represents the CustomUser with the MENTOR user type.

    Attributes:
            user: ForeignKey instance of the CustomUser model.
            preferred_industries: CharField indicating user industries preferred for work.
            useful_to_project: TextField instance indicates actions useful
                               for the development and maintenance of the project.
    """

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="mentor"
    )
    preferred_industries = models.CharField(max_length=4096, null=True, blank=True)
    useful_to_project = models.TextField(blank=True)

    class Meta(TypedModelMeta):
        verbose_name = "Ментор"
        verbose_name_plural = "Менторы"

    def __str__(self):
        return f"Mentor<{self.id}> - {self.user.first_name} {self.user.last_name}"


class Expert(AbstractUserWithRole):
    """
    Expert model

    Represents the CustomUser with the EXPERT user type.

    Attributes:
            preferred_industries: ManyToManyField indicating user industries preferred for work.
            useful_to_project: TextField instance indicates actions useful
                               for the development and maintenance of the project.
    """

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="expert"
    )

    preferred_industries = models.CharField(max_length=4096, null=True, blank=True)
    useful_to_project = models.TextField(blank=True)

    programs = models.ManyToManyField(
        "partner_programs.PartnerProgram", related_name="experts", blank=True
    )

    class Meta(TypedModelMeta):
        verbose_name = "Эксперт"
        verbose_name_plural = "Эксперты"

    def __str__(self):
        return f"Expert<{self.id}> - {self.user.first_name} {self.user.last_name}"


class Investor(AbstractUserWithRole):
    """
    Investor model

    Represents the CustomUser with the INVESTOR user type.

    Attributes:
            preferred_industries: ManyToManyField indicating user industries preferred for work.
            interaction_process_description: CharField describes the interaction process.

    """

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="investor"
    )
    preferred_industries = models.CharField(max_length=4096, null=True, blank=True)
    interaction_process_description = models.TextField(blank=True)

    class Meta(TypedModelMeta):
        verbose_name = "Инвестор"
        verbose_name_plural = "Инвесторы"

    def __str__(self):
        return f"Investor<{self.id}> - {self.user.first_name} {self.user.last_name}"


class UserLink(models.Model):
    """
    UserLink model

    Represents the user's link to some resource.

    Attributes:
            user: ForeignKey instance of the CustomUser model.
            link: URLField instance of the user's link to some resource.
    """

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="links",
    )
    link = models.URLField()

    def __str__(self):
        return f"UserLink<{self.id}> - {self.user.first_name} {self.user.last_name}"

    class Meta(TypedModelMeta):
        verbose_name = "Ссылка пользователя"
        verbose_name_plural = "Ссылки пользователей"
        unique_together = ("user", "link")


class AbstractUserExperience(models.Model):
    """Abstact help model for user work|education experience."""

    organization_name = models.CharField(
        max_length=255,
        verbose_name="Наименование организации",
    )
    description = models.TextField(
        max_length=1000,
        null=True,
        blank=True,
        verbose_name="Краткое описание",
    )
    entry_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[user_experience_years_range_validator],
        verbose_name="Год начала",
    )
    completion_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[user_experience_years_range_validator],
        verbose_name="Год завершения",
    )

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"id: {self.id} - ({self.user.first_name} {self.user.last_name} user_id: {self.user.id})"

    def clean(self) -> None:
        """Validate both years `entry` <`completion`"""
        super().clean()
        if self.entry_year and self.completion_year:
            if self.entry_year > self.completion_year:
                raise ValidationError(constants.USER_EXPERIENCE_YEAR_VALIDATION_MESSAGE)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class UserEducation(AbstractUserExperience):
    """
    User education model

    User education information.

    Attributes:
        user: FK CustomUser.
        education_level: CharField (choice) Education level.
        education_status: CharField (choice) Education status.
        organization_name: CharField Name of the organization.
        description: CharField Organization Description.
        entry_year: PositiveSmallIntegerField Year of admission.
        completion_year: PositiveSmallIntegerField Graduation year.
    """

    user = models.ForeignKey(
        to=CustomUser,
        on_delete=models.CASCADE,
        related_name="education",
        verbose_name="Пользователь",
    )
    education_level = models.CharField(
        max_length=256,
        choices=constants.UserEducationLevels.choices(),
        blank=True,
        null=True,
        verbose_name="Уровень образования",
    )
    education_status = models.CharField(
        max_length=256,
        choices=constants.UserEducationStatuses.choices(),
        blank=True,
        null=True,
        verbose_name="Статус по обучению",
    )

    class Meta:
        verbose_name = "Образование пользователя"
        verbose_name_plural = "Образование пользователя"


class UserWorkExperience(AbstractUserExperience):
    """
    User work experience.

    User work experience information.

    Attributes:
        user: FK CustomUser.
        job_position: CharField Job position.
        organization_name: CharField Name of the organization.
        description: CharField Organization Description.
        entry_year: PositiveSmallIntegerField Year of admission.
        completion_year: PositiveSmallIntegerField Year of dismissal.
    """

    user = models.ForeignKey(
        to=CustomUser,
        on_delete=models.CASCADE,
        related_name="work_experience",
        verbose_name="Пользователь",
    )
    job_position = models.CharField(
        max_length=256,
        null=True,
        blank=True,
        verbose_name="Должность",
    )

    class Meta:
        verbose_name = "Работа пользователя"
        verbose_name_plural = "Работа пользователя"


class UserLanguages(models.Model):
    """
    User knowledge of languages.

    User knowledge of languages information.

    Attributes:
        user: FK CustomUser.
        language: CharField(choise) languages.
        language_level: CharField(choise) language level.
    """

    user = models.ForeignKey(
        to=CustomUser,
        on_delete=models.CASCADE,
        related_name="user_languages",
        verbose_name="Пользователь",
    )
    language = models.CharField(
        max_length=50,
        choices=constants.UserLanguagesEnum.choices(),
        verbose_name="Язык",
    )
    language_level = models.CharField(
        max_length=50,
        choices=constants.UserLanguagesLevels.choices(),
        verbose_name="Уровнь владения",
    )

    class Meta:
        verbose_name = "Знание языка"
        verbose_name_plural = "Знание языков"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "language"],
                name="unique_user_language",
                violation_error_message=constants.UNIQUE_LANGUAGES_VALIDATION_MESSAGE,
            )
        ]

    def clean(self) -> None:
        """
        Custom validation to limit the number of languages per user to `USER_MAX_LANGUAGES_COUNT`.
        """
        super().clean()
        user_languages = self.user.user_languages.values_list("language", flat=True)
        if (self.language not in user_languages) and len(
            user_languages
        ) == constants.USER_MAX_LANGUAGES_COUNT:
            raise ValidationError(constants.COUNT_LANGUAGES_VALIDATION_MESSAGE)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"id: {self.id} - ({self.user.first_name} {self.user.last_name} user_id: {self.user.id})"


class UserSkillConfirmation(models.Model):
    """
    Store confirmations for skills.

    Attributes:
            skill_to_object: FK SkillToObject.
            confirmed_by: FK CustomUser.
            confirmed_at: DateTimeField.
    """

    skill_to_object = models.ForeignKey(
        "core.SkillToObject", on_delete=models.CASCADE, related_name="confirmations"
    )
    confirmed_by = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="skill_confirmations"
    )
    confirmed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["skill_to_object", "confirmed_by"],
                name="unique_skill_confirmed_by",
            )
        ]
        verbose_name = "Подтверждение навыка"
        verbose_name_plural = "Подтверждения навыков"

    def clean(self) -> None:
        # Check if the `skill_to_object` is related to a CustomUser.
        if not isinstance(self.skill_to_object.content_object, CustomUser):
            raise ValidationError("Skills can only be confirmed for users.")
        # Check that the user does not confirm their own skill.
        if self.confirmed_by == self.skill_to_object.content_object:
            raise ValidationError("User cant approve own skills.")
        return super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
