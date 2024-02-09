VERBOSE_NAME_TYPES = (
    ("str", "Текст"),
    ("int", "Целочисленное число"),
    ("float", "Число с плавающей точкой"),
    ("bool", "Да или нет"),
)

GET_TYPE_FROM_STRING = {"str": str, "int": int, "float": float, "bool": bool}
