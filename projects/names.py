DEFAULT_PROJECT_NAME = "Проект без названия"


def normalize_project_name(name: str | None) -> str:
    """Give unnamed projects a searchable name without changing existing titles."""
    return name if name and name.strip() else DEFAULT_PROJECT_NAME
