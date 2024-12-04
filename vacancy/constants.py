from enum import Enum


class ChoicesMixin:

    @classmethod
    def choices(cls):
        """Return a list of tuples (value, display_name) for choices."""
        return [(item.name.lower(), item.value) for item in cls]

    @classmethod
    def from_display(cls, display_value):
        """Convert display value to Enum name."""
        for item in cls:
            if item.value == display_value:
                return item.name.lower()
            elif display_value is None:
                return None
        raise ValueError(f"Invalid display value: {display_value}")

    @classmethod
    def to_display(cls, name_value):
        """Convert Enum name to display value."""
        for item in cls:
            if item.name.lower() == name_value:
                return item.value
            elif name_value is None:
                return None
        raise ValueError(f"Invalid name value: {name_value}")


class WorkExperience(ChoicesMixin, Enum):

    NO_EXPERIENCE: str = "без опыта"
    UP_TO_A_YEAR: str = "до 1 года"
    FROM_ONE_TO_THREE_YEARS: str = "от 1 года до 3 лет"
    FROM_THREE_YEARS: str = "от 3 лет и более"


class WorkSchedule(ChoicesMixin, Enum):

    FULL_TIME: str = "полный рабочий день"
    SHIFT_WORK: str = "сменный график"
    FLEXIBLE_SCHEDULE: str = "гибкий график"
    PART_TIME: str = "частичная занятость"
    INTERNSHIP: str = "стажировка"


class WorkFormat(ChoicesMixin, Enum):

    REMOTE: str = "удаленная работа"
    OFFICE: str = "работа в офисе"
    HYBRID: str = "смешанный формат"
