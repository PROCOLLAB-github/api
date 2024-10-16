from enum import Enum

from django.conf import settings


class OnboardingStage(Enum):
    intro = 0
    skills = 1
    account_type = 2
    completed = None


ADMIN = 0
MEMBER = 1
MENTOR = 2
EXPERT = 3
INVESTOR = 4

VERBOSE_USER_TYPES = (
    (MEMBER, "Участник"),
    (MENTOR, "Ментор"),
    (EXPERT, "Консультант"),
    (INVESTOR, "Инвестор"),
)

VERBOSE_ROLE_TYPES = (
    (MENTOR, "Ментор"),
    (EXPERT, "Консультант"),
    (INVESTOR, "Инвестор"),
)

VERIFY_EMAIL_REDIRECT_URL = "https://app.procollab.ru/auth/verification/"


PROTOCOL = "https"
if settings.DEBUG:
    PROTOCOL = "http"


NOT_VALID_NUMBER_MESSAGE: str = (
    "Номер телефона должен соответствовать международному стандарту. "
    "Пример: +7 XXX XX-XX-XX | +375XXXXXXXXX | +995 (XXX) XX-XX-XX"
)


class UserEducationLevels(Enum):
    """User education level lists to select from."""

    SCHOOL = "Среднее общее образование"
    COLLEGE = "Среднее профессиональное образование"
    HIGHER_BACALAVR = "Высшее образование – бакалавриат, специалитет"
    HIGHER_MAGISTRACY = "Высшее образование – магистратура"
    HIGHER_POSTGRADUATE = "Высшее образование – аспирантура"

    @classmethod
    def choices(cls):
        """Return a list of tuples (value, display_name) for choices."""
        return [(item.value, item.value) for item in cls]


class UserEducationStatuses(Enum):
    """User education status lists to select from."""

    APPRENTICE = "Ученик"
    STUDENT = "Студент"
    GRADUATE = "Выпускник"

    @classmethod
    def choices(cls):
        """Return a list of tuples (value, display_name) for choices."""
        return [(item.value, item.value) for item in cls]


USER_EXPERIENCE_YEAR_VALIDATION_MESSAGE: str = "Год начала не может быть больше года завершения"

# Working with user skills:
USER_MAX_SKILL_QUANTITY: int = 20
USER_SKILL_QUANTITY_VALIDATIONS_MESSAGE: str = "Необходимо указать от 1 до 20 навыков"

# Working with user languages:
USER_MAX_LANGUAGES_COUNT: int = 4
COUNT_LANGUAGES_VALIDATION_MESSAGE: str = "Пользователь не может указать более 4 языков"
UNIQUE_LANGUAGES_VALIDATION_MESSAGE: str = "Нельзя добавлять дубликаты языков"


class UserLanguagesEnum(Enum):
    """User languages lists to select from."""

    ENGLISH = "Английский"
    SPANISCH = "Испанский"
    ITALIAN = "Итальянский"
    GERMAN = "Немецкий"
    JAPANESE = "Японский"
    CHINESE = "Китайский"
    ARABIC = "Арабский"
    SWEDISH = "Шведский"
    POLISH = "Польский"
    CZECH = "Чешский"
    RUSSIAN = "Русский"
    FRENCH = "Французский"

    @classmethod
    def choices(cls):
        """Return a list of tuples (value, display_name) for choices."""
        return [(item.value, item.value) for item in cls]


class UserLanguagesLevels(Enum):
    """
    User languages levels lists to select from.
    (Level value in Cyrillic)
    """

    А1 = "А1"
    А2 = "А2"
    B1 = "B1"
    B2 = "B2"
    С1 = "С1"
    С2 = "С2"

    @classmethod
    def choices(cls):
        """Return a list of tuples (value, display_name) for choices."""
        return [(item.value, item.value) for item in cls]
