from typing import Literal

VERBOSE_TYPES = (
    ("str", "Текст"),
    ("int", "Целочисленное число"),
    ("float", "Число с плавающей точкой"),
    ("bool", "Да или нет"),
)

validatable_types_names = Literal["bool", "str", "int", "float"]


NUMERIC_TYPES = ["int", "float"]
