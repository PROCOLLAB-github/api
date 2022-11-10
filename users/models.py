from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from industries.models import Industry
from users.helpers import (
    ADMIN,
    EXPERT,
    INVESTOR,
    MEMBER,
    MENTOR,
    VERBOSE_ROLE_TYPES,
    VERBOSE_USER_TYPES,
)
from users.managers import CustomUserManager


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
        datetime_updated: A DateTimeField indicating date of update.
        datetime_created: A DateTimeField indicating date of creation.
    """

    ADMIN = ADMIN
    MEMBER = MEMBER
    MENTOR = MENTOR
    EXPERT = EXPERT
    INVESTOR = INVESTOR

    username = None
    email = models.EmailField(blank=False, unique=True)
    first_name = models.CharField(max_length=255, blank=False)
    last_name = models.CharField(max_length=255, blank=False)
    password = models.CharField(max_length=255, blank=False)
    is_active = models.BooleanField(default=False, editable=False)
    user_type = models.PositiveSmallIntegerField(
        choices=VERBOSE_USER_TYPES,
        default=get_default_user_type,
    )

    patronymic = models.CharField(max_length=255, blank=True)
    avatar = models.URLField(null=True, blank=True)
    birthday = models.DateField(null=True, blank=True)
    about_me = models.TextField(blank=True)
    status = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255, blank=True)
    organization = models.CharField(max_length=255, blank=True)

    datetime_updated = models.DateTimeField(null=False, auto_now=True)
    datetime_created = models.DateTimeField(null=False, auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def get_member_key_skills(self):
        if self.user_type == CustomUser.MEMBER:
            return str(self.member.key_skills)
        return ""

    def __str__(self):
        return f"User<{self.id}> - {self.first_name} {self.last_name}"


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

    class Meta:
        abstract = True


class Member(models.Model):
    """
    Member model

    Represents the CustomUser with the MEMBER user type.

    Attributes:
        user: ForeignKey instance of the CustomUser model.
        key_skills: CharField instance indicating member key skills.
        useful_to_project: TextField instance indicates actions useful
                           for the development and maintenance of the project.
        preferred_industries: ManyToManyField indicating user industries preferred for work.
    """

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="member"
    )

    key_skills = models.CharField(max_length=512, blank=True)
    useful_to_project = models.TextField(blank=True)
    preferred_industries = models.ManyToManyField(
        Industry, blank=True, related_name="members"
    )

    def __str__(self):
        return f"Member<{self.id}> - {self.user.first_name} {self.user.last_name}"


class Mentor(AbstractUserWithRole):
    """
    Mentor model

    Represents the CustomUser with the MENTOR user type.

    Attributes:
            user: ForeignKey instance of the CustomUser model.
            useful_to_project: TextField instance indicates actions useful
                               for the development and maintenance of the project.
    """

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="mentor"
    )
    # CustomUser already has a field called "organization"
    # job = models.CharField(max_length=255, blank=True)
    useful_to_project = models.TextField(blank=True)

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

    preferred_industries = models.ManyToManyField(
        Industry, blank=True, related_name="experts"
    )
    useful_to_project = models.TextField(blank=True)

    # TODO reviews

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

    preferred_industries = models.ManyToManyField(
        Industry, blank=True, related_name="investors"
    )
    interaction_process_description = models.TextField(blank=True)

    def __str__(self):
        return f"Investor<{self.id}> - {self.user.first_name} {self.user.last_name}"


@receiver(post_save, sender=CustomUser)
def create_or_update_user_types(sender, instance, created, **kwargs):
    if created:
        if instance.user_type == CustomUser.MEMBER:
            Member.objects.create(user=instance)
        elif instance.user_type == CustomUser.MENTOR:
            Mentor.objects.create(user=instance)
        elif instance.user_type == CustomUser.EXPERT:
            Expert.objects.create(user=instance)
        elif instance.user_type == CustomUser.INVESTOR:
            Investor.objects.create(user=instance)
