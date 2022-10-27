from django.contrib.auth.models import AbstractUser
from django.db import models

from users.managers import CustomUserManager


class UserType(models.Model):
    """
    UserType model

    Indicating type of user.

    Attributes:
        id: PositiveSmallIntegerField indicating user type according to VERBOSE_USER_TYPES.


    """

    ADMIN = 0
    REGULAR = 1
    MENTOR = 2
    EXPERT = 3
    INVESTOR = 4

    VERBOSE_USER_TYPES = (
        (ADMIN, "Администратор"),
        (REGULAR, "Участник"),
        (MENTOR, "Ментор"),
        (EXPERT, "Эксперт"),
        (INVESTOR, "Инвестор"),
    )

    id = models.PositiveSmallIntegerField(choices=VERBOSE_USER_TYPES, primary_key=True)

    def __str__(self):
        return f"UserType<{self.id}> - {self.get_id_display()}"


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
        organization: CharField instance the user's name organization.
        tags: CharField instance tags. TODO
    """

    username = None
    email = models.EmailField(blank=False, unique=True)
    first_name = models.CharField(max_length=255, blank=False)
    last_name = models.CharField(max_length=255, blank=False)
    password = models.CharField(max_length=255, blank=False)
    is_active = models.BooleanField(default=False, editable=False)
    datetime_updated = models.DateTimeField(auto_now=True)

    patronymic = models.CharField(max_length=255, blank=True)  # Отчество
    avatar = models.URLField(null=True, blank=True)
    birthday = models.DateField(null=True)
    about_me = models.TextField(blank=True)
    status = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255, blank=True)
    organization = models.CharField(max_length=255, blank=True)

    key_skills = models.CharField(max_length=255, blank=True)  # TODO
    useful_to_project = models.CharField(max_length=255, blank=True)
    speciality = models.CharField(max_length=255, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return f"User<{self.id}> - {self.first_name} {self.last_name}"
