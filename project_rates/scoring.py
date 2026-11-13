"""Процентные веса и нормализация; один контракт для API, моделей и admin."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

LEGACY = "legacy"
WEIGHTED = "weighted_percent"
SCORING_MODES = ((LEGACY, "Сумма исходных баллов"), (WEIGHTED, "Веса, итог от 0 до 100"))
NUMERIC_TYPES = ("int", "float")


def decimal_number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Укажите конечное число.") from error
    if not result.is_finite():
        raise ValueError("Укажите конечное число.")
    return result


def validate_weight(criterion):
    value = getattr(criterion, "weight_percent", None)
    if value is None:
        return
    weight = decimal_number(value)
    if criterion.type not in NUMERIC_TYPES:
        raise ValueError("Вес можно задать только числовому критерию.")
    if not 0 < weight <= 100 or weight != weight.quantize(Decimal("0.01")):
        raise ValueError(
            "Укажите вес больше 0 и не больше 100%, до двух знаков после запятой."
        )


def percentage_criteria(criteria):
    specifications = []
    for criterion in criteria:
        validate_weight(criterion)
        if criterion.type not in NUMERIC_TYPES:
            continue
        if getattr(criterion, "weight_percent", None) is None:
            raise ValueError("Укажите вес каждого числового критерия.")
        low = decimal_number(criterion.min_value)
        high = decimal_number(criterion.max_value)
        if high <= low:
            raise ValueError("Для весов нужен конечный максимум строго больше минимума.")
        specifications.append(
            (criterion, low, high, decimal_number(criterion.weight_percent))
        )
    if not specifications or sum(row[3] for row in specifications) != Decimal("100"):
        raise ValueError("Сумма весов числовых критериев должна быть ровно 100%.")
    return specifications


def validate_configuration(program, criteria=None):
    if program.evaluation_scoring_mode == LEGACY:
        return
    if program.evaluation_scoring_mode != WEIGHTED:
        raise ValidationError({"evaluation_scoring_mode": "Выберите способ расчета."})
    try:
        percentage_criteria(
            list(program.criterias.all()) if criteria is None else criteria
        )
    except ValueError as error:
        raise ValidationError({"evaluation_scoring_mode": str(error)}) from error


def weighted_values(specifications, values):
    return {
        criterion.pk: (decimal_number(values[criterion.pk]) - low) / (high - low) * weight
        for criterion, low, high, weight in specifications
    }
