from rate_projects.constants import GET_TYPE_FROM_STRING


def find_filled_field(data):
    filled_fields = []
    for field in ["value_int", "value_bool", "value_str", "value_float"]:
        if data[field] is not None:
            filled_fields.append(data[field])
    return filled_fields


class ProjectScoreValidate:
    def __init__(self, **kwargs):
        self.criteria_type = kwargs.get("criteria_type")
        self.value_int = kwargs.get("value_int")
        self.value_str = kwargs.get("value_str")
        self.value_bool = kwargs.get("value_bool")
        self.value_float = kwargs.get("value_float")
        self.criteria_min_value = kwargs.get("criteria_min_value")
        self.criteria_max_value = kwargs.get("criteria_max_value")

        self._validate_quantity_filled_fields()
        self._validate_numeric_fields()

    @property
    def _find_filled_field(self):
        filled_fields = []
        for field in ["value_int", "value_bool", "value_str", "value_float"]:
            if getattr(self, field) is not None:
                filled_fields.append(getattr(self, field))
        return filled_fields

    def _validate_quantity_filled_fields(self):
        filled_fields = self._find_filled_field
        if len(filled_fields) > 1:
            raise ValueError("Должно быть заполнено менее 2-ух полей!")

        if not isinstance(filled_fields[0], GET_TYPE_FROM_STRING.get(self.criteria_type)):
            raise ValueError("Тип введённых данных не совпадает с требуемым!")

    def _validate_numeric_fields(self):
        added_value = self._find_filled_field[0]

        if self.criteria_type != "bool" and isinstance(added_value, (int, float)):
            if (
                self.criteria_min_value is not None
                and self.criteria_min_value > added_value
            ):
                raise ValueError("Оценка этого критерия принизила допустимые значения!")
            elif (
                self.criteria_max_value is not None
                and self.criteria_max_value < added_value
            ):
                raise ValueError("Оценка этого критерия превысила допустимые значения!")
