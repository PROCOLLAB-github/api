class ProjectScoreValidate:
    def __init__(self, **kwargs):
        self.criteria_type = kwargs.get("criteria_type")
        self.value = kwargs.get("value")
        self.criteria_min_value = kwargs.get("criteria_min_value")
        self.criteria_max_value = kwargs.get("criteria_max_value")

        self._validate_data_type()
        self._validate_numeric_limits()

    def _validate_data_type(self):
        if self.criteria_type in ["float", "int"]:
            try:
                float(self.value)
            except ValueError:
                raise ValueError("Введённое значение не соответствует формату!")

        elif (self.criteria_type == "bool") and (self.value not in ["True", "False"]):
            raise TypeError("Введённое значение не соответствует формату!")

    def _validate_numeric_limits(self):
        if self.criteria_type in ["int", "float"]:
            if self.criteria_min_value is not None and self.criteria_min_value > float(
                self.value
            ):
                raise ValueError("Оценка этого критерия принизила допустимые значения!")
            elif self.criteria_max_value is not None and self.criteria_max_value < float(
                self.value
            ):
                raise ValueError("Оценка этого критерия превысила допустимые значения!")
