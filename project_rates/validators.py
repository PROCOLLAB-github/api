from project_rates.constants import validatable_types_names, NUMERIC_TYPES


class ProjectScoreValidator:
    @classmethod
    def validate(cls, **kwargs):
        criteria_type: validatable_types_names = kwargs.get("criteria_type")
        value: str = kwargs.get("value")
        criteria_min_value: float | None = kwargs.get("criteria_min_value")
        criteria_max_value: float | None = kwargs.get("criteria_max_value")

        cls._validate_data_type(criteria_type, value)
        if criteria_type in NUMERIC_TYPES:
            cls._validate_numeric_limits(criteria_min_value, criteria_max_value, value)

    @staticmethod
    def _validate_data_type(criteria_type: str, value: str):
        if criteria_type in NUMERIC_TYPES:
            try:
                float(value)
            except ValueError:
                raise ValueError("Введённое значение не соответствует формату!")
            except TypeError:
                raise TypeError("Вы не ввели никакие данные!")

        elif (criteria_type == "bool") and (value not in ["True", "False"]):
            raise TypeError("Введённое значение не соответствует формату!")

    @staticmethod
    def _validate_numeric_limits(
        min_value: float | None, max_value: float | None, value: str
    ):
        if min_value is not None and min_value > float(value):
            raise ValueError("Оценка этого критерия принизила допустимые значения!")
        elif max_value is not None and max_value < float(value):
            raise ValueError("Оценка этого критерия превысила допустимые значения!")
