from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from partner_programs.helpers import date_to_iso
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from vacancy.mapping import MessageTypeEnum, UserProgramRegisterParams
from vacancy.tasks import send_email

User = get_user_model()

EXTERNAL_REGISTRATION_USER_FIELDS = (
    "first_name",
    "last_name",
    "patronymic",
    "city",
)


class ProgramRegistrationError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _send_program_registration_email(user, program: PartnerProgram) -> None:
    send_email.delay(
        UserProgramRegisterParams(
            message_type=MessageTypeEnum.REGISTERED_PROGRAM_USER.value,
            user_id=user.id,
            program_name=program.name,
            program_id=program.id,
            schema_id=2,
        )
    )


def register_user_to_program(
    *,
    program: PartnerProgram,
    user: User,
    data,
) -> PartnerProgramUserProfile:
    if program.datetime_registration_ends < timezone.now():
        raise ProgramRegistrationError("Registration period has ended.")

    try:
        user_profile = PartnerProgramUserProfile.objects.create(
            partner_program_data=data,
            user=user,
            partner_program=program,
        )
    except IntegrityError:
        raise ProgramRegistrationError("User already registered to this program.")

    _send_program_registration_email(user, program)
    return user_profile


def create_user_and_register_to_program(
    *,
    program: PartnerProgram,
    data,
) -> PartnerProgramUserProfile:
    email = data.get("email") if data.get("email") else data.get("email_")
    if not email:
        raise ProgramRegistrationError("You need to pass an email address.")

    password = data.get("password")
    if not password:
        raise ProgramRegistrationError("You need to pass a password.")

    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "birthday": date_to_iso(data.get("birthday", "01-01-1900")),
            "is_active": True,  # bypass email verification for external forms
            "onboarding_stage": None,  # bypass onboarding for external forms
            "verification_date": timezone.now(),  # bypass manual verification
            **{
                field_name: data.get(field_name, "")
                for field_name in EXTERNAL_REGISTRATION_USER_FIELDS
            },
        },
    )
    if created:
        user.set_password(password)
        user.save()

    user_profile_program_data = {
        k: v
        for k, v in data.items()
        if k not in EXTERNAL_REGISTRATION_USER_FIELDS and k != "password"
    }
    try:
        user_profile = PartnerProgramUserProfile.objects.create(
            partner_program_data=user_profile_program_data,
            user=user,
            partner_program=program,
        )
    except IntegrityError:
        raise ProgramRegistrationError(
            "User has already registered in this program."
        )

    _send_program_registration_email(user, program)
    return user_profile
