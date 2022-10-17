from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from .managers import CustomUserManager


class CustomUser(AbstractUser):
    username = None
    email = models.EmailField(max_length=255, blank=False, unique=True)
    first_name = models.CharField(max_length=255, blank=False)
    last_name = models.CharField(max_length=255, blank=False)
    password = models.CharField(max_length=255, blank=False)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []


class UserInfo(models.Model):
    """
    User model
    Attributes:
        email: CharField instance of user's email.
        username: CharField instance of the username.
        surname: CharField instance of the user last name.
        patronymic: CharField instance of the user patronymic.
        birthday: DateField instance of the user's birthday.
        photo_address: ImageField instance of the user's photo containing url.
        key_skills: CharField instance of user skills containing keys.
        useful_to_project: CharField instance of the something useful... TODO
        about_me: TextField instance contains information about the user.
        status: CharField instance notifies about the user's status.
        speciality: CharField instance the user's specialty.
        city: CharField instance the user's name city.
        region: CharField instance the user's name region.
        organization: CharField instance the user's name organization.
        achievements: JSONField instance containing of the user's achievements.
        tags: CharField instance tags. TODO
        user: ForeignKey instance which
    """
    email = models.EmailField(max_length=255)
    patronymic = models.CharField(max_length=255)
    birthday = models.DateField(null=True)
    photo_address = models.ImageField(upload_to='photos/%Y/%m/%d/')
    key_skills = models.CharField(max_length=255)  # TODO
    useful_to_project = models.CharField(max_length=255)
    about_me = models.TextField()
    status = models.CharField(max_length=255)
    speciality = models.CharField(max_length=255)
    city = models.CharField(max_length=255)
    region = models.CharField(max_length=255)
    organization = models.CharField(max_length=255)
    achievements = models.JSONField(null=True)
    tags = models.CharField(max_length=255)
    user = models.OneToOneField(CustomUser,
                                on_delete=models.CASCADE)

    def __str__(self):
        return f"User<{self.email}>"


@receiver(post_save, sender=CustomUser)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserInfo.objects.create(email=instance.email, user_id=instance.pk)
    instance.userinfo.save()
