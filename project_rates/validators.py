from project_rates.constants import ValidatableTypesNames, NumericTypes


class ProjectScoreValidator:
    @classmethod
    def validate(cls, **kwargs):
        criteria_type: ValidatableTypesNames = kwargs.get("criteria_type")
        value: str = kwargs.get("value")
        criteria_min_value: float | None = kwargs.get("criteria_min_value")
        criteria_max_value: float | None = kwargs.get("criteria_max_value")

        cls._validate_data_type(criteria_type, value)
        if criteria_type in NumericTypes:
            cls._validate_numeric_limits(
                criteria_min_value, criteria_max_value, float(value)
            )

    @staticmethod
    def _validate_data_type(criteria_type: str, value: str):
        if criteria_type in NumericTypes:
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
        min_value: float | None, max_value: float | None, value: float
    ):
        if min_value is not None and min_value > value:
            raise ValueError("Оценка этого критерия ниже допустимого значения!")
        elif max_value is not None and max_value < value:
            raise ValueError("Оценка этого критерия превысила допустимое значение!")
