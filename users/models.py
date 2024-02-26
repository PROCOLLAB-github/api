from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import QuerySet
from django_stubs_ext.db.models import TypedModelMeta

from users.constants import (
    ADMIN,
    EXPERT,
    INVESTOR,
    MEMBER,
    MENTOR,
    VERBOSE_ROLE_TYPES,
    VERBOSE_USER_TYPES,
    OnboardingStage,
)
from users.managers import (
    CustomUserManager,
    UserAchievementManager,
    LikesOnProjectManager,
)
from users.validators import user_birthday_validator, user_name_validator


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
        organization: CharField instance the user's place of study or work.
        speciality: CharField instance the user's specialty.
        datetime_updated: A DateTimeField indicating date of update.
        datetime_created: A DateTimeField indicating date of creation.
    """

    ADMIN = ADMIN
    MEMBER = MEMBER
    MENTOR = MENTOR
    EXPERT = EXPERT
    INVESTOR = INVESTOR

    username = None
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=255, validators=[user_name_validator])
    last_name = models.CharField(max_length=255, validators=[user_name_validator])
    password = models.CharField(max_length=255)
    is_active = models.BooleanField(default=False, editable=False)
    user_type = models.PositiveSmallIntegerField(
        choices=VERBOSE_USER_TYPES,
        default=get_default_user_type,
    )

    ordering_score = models.PositiveIntegerField(
        default=0,
        editable=False,
    )
    patronymic = models.CharField(
        max_length=255, validators=[user_name_validator], null=True, blank=True
    )
    key_skills = models.CharField(max_length=512, null=True, blank=True)
    avatar = models.URLField(null=True, blank=True)
    birthday = models.DateField(
        validators=[user_birthday_validator],
    )
    about_me = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=255, null=True, blank=True)
    region = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=255, null=True, blank=True)
    organization = models.CharField(max_length=255, null=True, blank=True)
    v2_speciality = models.ForeignKey(
        on_delete=models.SET_NULL,
        null=True,
        related_name="users",
        to="core.Specialization",
    )
    speciality = models.CharField(max_length=255, null=True, blank=True)
    onboarding_stage = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        editable=False,
        default=OnboardingStage.intro.value,
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

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def calculate_ordering_score(self) -> int:
        """
        Calculate ordering score of the user, e.g. how full their profile is.

        Returns:
            int: ordering score of the user.
        """
        score = 0
        if self.avatar:
            score += 10
        if self.key_skills:
            score += 7
        if self.about_me:
            score += 6
        if self.region:
            score += 4
        if self.city:
            score += 4
        if self.organization:
            score += 6
        if self.speciality:
            score += 7
        return score

    def get_project_chats(self) -> QuerySet:
        from chats.models import ProjectChat

        user_project_ids = self.collaborations.all().values_list("project_id", flat=True)
        return ProjectChat.objects.filter(project__in=user_project_ids)

    def get_key_skills(self) -> list[str]:
        return [skill.strip() for skill in self.key_skills.split(",") if skill.strip()]

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __str__(self) -> str:
        return f"User<{self.id}> - {self.first_name} {self.last_name}"

    class Meta(TypedModelMeta):
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        # order by count of fields inputted, like avatar, key_skills, about_me, etc.
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
        choices=VERBOSE_ROLE_TYPES,
        null=True,
    )
    second_additional_role = models.PositiveSmallIntegerField(
        choices=VERBOSE_ROLE_TYPES,
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
