from datetime import datetime, time, timedelta

from django.utils import timezone

from mailing.models import MailingSchema
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from users.models import CustomUser


def aware_datetime(dt_date, hour: int = 12):
    return timezone.make_aware(
        datetime.combine(dt_date, time(hour=hour)),
        timezone.get_current_timezone(),
    )


def create_user(email: str = "mailing-user@example.com", **overrides) -> CustomUser:
    defaults = {
        "email": email,
        "password": "test-password-12345",
        "first_name": "Test",
        "last_name": "User",
        "birthday": "2000-01-01",
        "is_active": True,
    }
    defaults.update(overrides)
    return CustomUser.objects.create_user(**defaults)


def create_program(**overrides) -> PartnerProgram:
    today = timezone.localdate()
    defaults = {
        "name": "Mailing Program",
        "tag": "mailing-program",
        "city": "Moscow",
        "datetime_registration_ends": aware_datetime(today + timedelta(days=10)),
        "datetime_started": aware_datetime(today - timedelta(days=10)),
        "datetime_finished": aware_datetime(today + timedelta(days=40)),
    }
    defaults.update(overrides)
    return PartnerProgram.objects.create(**defaults)


def register_program_user(
    user: CustomUser,
    program: PartnerProgram,
    registered_on,
) -> PartnerProgramUserProfile:
    profile = PartnerProgramUserProfile.objects.create(
        user=user,
        partner_program=program,
        partner_program_data={},
    )
    PartnerProgramUserProfile.objects.filter(id=profile.id).update(
        datetime_created=aware_datetime(registered_on)
    )
    profile.refresh_from_db()
    return profile


def create_mailing_schema(**overrides) -> MailingSchema:
    defaults = {
        "name": "Default mailing schema",
        "schema": {
            "title": {"title": "Title", "default": "Default title"},
            "text": {"title": "Text"},
            "button_text": {"title": "Button text", "default": "Open"},
        },
        "template": "<h1>{{ title }}</h1><p>{{ text }}</p>{{ user.email }}",
    }
    defaults.update(overrides)
    return MailingSchema.objects.create(**defaults)
