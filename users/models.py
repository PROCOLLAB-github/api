from django.contrib.auth.models import AbstractUser
from django.db import models
from industries.models import Industry

from users.managers import CustomUserManager


def get_default_user_type():
    return CustomUser.MEMBER


class CustomUser(AbstractUser):
    """
    User model

    Attributes:
        email: CharField instance of user's email.
        first_name: CharField instance of the user first name.
        last_name: CharField instance of the user last name.
        patronymic: CharField instance of the user patronymic.
        password: CharField instance of the user password.
        is_active: Boolean indicating if user confirmed email.
        birthday: DateField instance of the user's birthday.
        avatar: URLField instance of the user's avatar url.
        key_skills: CharField instance of user skills containing keys.
        useful_to_project: CharField instance of the something useful... TODO
        about_me: TextField instance contains information about the user.
        status: CharField instance notifies about the user's status.
        speciality: CharField instance the user's specialty.
        city: CharField instance the user's name city.
        region: CharField instance the user's name region.
        organization: CharField instance the user's place of study or work.
        tags: CharField instance tags. TODO
    """

    ADMIN = 0
    MEMBER = 1
    MENTOR = 2
    EXPERT = 3
    INVESTOR = 4

    VERBOSE_USER_TYPES = (
        (ADMIN, "Администратор"),
        (MEMBER, "Участник"),
        (MENTOR, "Ментор"),
        (EXPERT, "Эксперт"),
        (INVESTOR, "Инвестор"),
    )

    username = None
    email = models.EmailField(blank=False, unique=True)
    first_name = models.CharField(max_length=255, blank=False)
    last_name = models.CharField(max_length=255, blank=False)
    password = models.CharField(max_length=255, blank=False)
    is_active = models.BooleanField(default=False, editable=False)
    datetime_updated = models.DateTimeField(auto_now=True)

    user_type = models.PositiveSmallIntegerField(
        choices=VERBOSE_USER_TYPES,
        default=get_default_user_type,
    )

    patronymic = models.CharField(max_length=255, blank=True)  # Отчество
    avatar = models.URLField(null=True, blank=True)
    birthday = models.DateField(null=True)
    about_me = models.TextField(blank=True)
    status = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255, blank=True)
    organization = models.CharField(max_length=255, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return f"User<{self.id}> - {self.first_name} {self.last_name}"


class Member(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)

    key_skills = models.CharField(max_length=255, blank=True)  # TODO
    useful_to_project = models.TextField(blank=True)
    speciality = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Member<{self.id}> - {self.first_name} {self.last_name}"


class Mentor(models.Model):
    """
    Mentor model

    Attributes:
            job: CharField instance current user job.
            useful_to_project: CharField instance some text.
    """

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="mentors")

    job = models.CharField(max_length=255, blank=True)
    useful_to_project = models.TextField(blank=True)

    def __str__(self):
        return f"Mentor<{self.id}> - {self.first_name} {self.last_name}"


class Expert(models.Model):
    """
    Expert model

    Attributes:
            preferred_industries: CharField instance TODO
            useful_to_project: CharField instance TODO
    """

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)

    preferred_industries = models.ManyToManyField(
        Industry, blank=True, related_name="experts"
    )
    useful_to_project = models.TextField(blank=True)

    # TODO reviews

    def __str__(self):
        return f"Expert<{self.id}> - {self.first_name} {self.last_name}"


class Investor(models.Model):
    """
    Investor model

    Attributes:
            preferred_industries: CharField instance TODO
            interaction_process_description: CharField describes the interaction process.

    """

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)

    preferred_industries = models.ManyToManyField(
        Industry, blank=True, related_name="investors"
    )
    interaction_process_description = models.TextField(blank=True)

    def __str__(self):
        return f"Investor<{self.id}> - {self.first_name} {self.last_name}"
