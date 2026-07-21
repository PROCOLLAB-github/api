def extend_with_env_list(base_values: list[str], raw_value: str) -> list[str]:
    """Добавляет к базовому списку непустые значения из env-строки через запятую."""
    extra_values = [value.strip() for value in raw_value.split(",") if value.strip()]

    return [*base_values, *extra_values]
