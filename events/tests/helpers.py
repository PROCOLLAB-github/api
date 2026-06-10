from datetime import date, timedelta
from uuid import uuid4

from django.utils import timezone

from events.models import Event
from users.models import CustomUser


def build_user(
    *,
    prefix: str = "events-user",
    is_staff: bool = False,
    is_active: bool = True,
) -> CustomUser:
    user = CustomUser.objects.create_user(
        email=f"{prefix}-{uuid4().hex}@example.com",
        password="very_strong_password",
        first_name="Иван",
        last_name="Иванов",
        birthday=date(2000, 1, 1),
    )
    user.is_staff = is_staff
    user.is_active = is_active
    user.save(update_fields=["is_staff", "is_active"])
    return user


def build_staff_user(*, prefix: str = "events-staff") -> CustomUser:
    return build_user(prefix=prefix, is_staff=True)


def build_event_payload(**overrides) -> dict:
    payload = {
        "title": "Мероприятие",
        "text": "Полное описание мероприятия",
        "short_text": "Краткое описание",
        "cover_url": "https://example.com/event-cover.jpg",
        "datetime_of_event": (
            timezone.now() + timedelta(days=7)
        ).isoformat(),
        "tags": ["events", "procollab"],
        "event_type": 1,
        "prize": "Диплом участника",
    }
    payload.update(overrides)
    return payload


def build_event(**overrides) -> Event:
    tags = overrides.pop("tags", ["events"])
    defaults = {
        "title": "Мероприятие",
        "text": "Полное описание мероприятия",
        "short_text": "Краткое описание",
        "cover_url": "https://example.com/event-cover.jpg",
        "datetime_of_event": timezone.now() + timedelta(days=7),
        "event_type": 1,
        "prize": "Диплом участника",
    }
    defaults.update(overrides)
    event = Event.objects.create(**defaults)
    event.tags.set(tags)
    return event
