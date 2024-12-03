from enum import Enum


class ChoicesMixin:

    @classmethod
    def choices(cls):
        """Return a list of tuples (value, display_name) for choices."""
        return [(item.value, item.value) for item in cls]


class WorkExperience(ChoicesMixin, Enum):

    NO_EXPERIENCE: str = "Без опыта"
    UP_TO_A_YEAR: str = "До 1 года"
    FROM_ONE_TO_THREE_YEARS: str = "От 1 года до 3 лет"
    FROM_THREE_YEARS: str = "От 3 лет и более"


class WorkSchedule(ChoicesMixin, Enum):

    FULL_TIME: str = "Полный рабочий день"
    SHIFT_WORK: str = "Сменный график"
    FLEXIBLE_SCHEDULE: str = "Гибкий график"
    PART_TIME: str = "Частичная занятость"
    INTERNSHIP: str = "Стажировка"


class WorkFormat(ChoicesMixin, Enum):

    REMOTE: str = "Удаленная работа"
    OFFICE: str = "Работа в офисе"
    HYBRID: str = "Смешанная"
