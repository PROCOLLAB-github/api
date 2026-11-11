"""Общие правила завершенности, баллов и мест для проектов и решений."""

from decimal import Decimal, ROUND_HALF_UP

from project_rates.validators import ProjectScoreValidator
from project_rates.scoring import LEGACY, WEIGHTED, percentage_criteria, weighted_values


def rounded(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def numeric(value):
    return float(value) if value is not None else None


def valid_score(criterion, value):
    try:
        ProjectScoreValidator.validate(
            criteria_type=criterion.type,
            value=value,
            criteria_min_value=criterion.min_value,
            criteria_max_value=criterion.max_value,
        )
        return True
    except (TypeError, ValueError):
        return False


def complete_values(criteria, values):
    return bool(criteria) and all(
        criterion.pk in values and valid_score(criterion, values[criterion.pk])
        for criterion in criteria
    )


def evaluation_totals(criteria, values_by_user, *, scoring_mode=LEGACY):
    """Сохраняет порядок округления существующего results_data, включая float totals."""
    if scoring_mode == WEIGHTED:
        specifications = percentage_criteria(criteria)
        evaluations, exact_totals, contributions = {}, {}, {}
        for user_id, values in values_by_user.items():
            complete = complete_values(criteria, values)
            parts = weighted_values(specifications, values) if complete else {}
            total = sum(parts.values(), Decimal("0")) if complete else None
            evaluations[user_id] = dict(complete=complete, total=numeric(total))
            if complete:
                exact_totals[user_id] = total
                contributions[user_id] = parts
        completed = list(exact_totals)
        return dict(
            evaluations=evaluations,
            completed=len(completed),
            score=numeric(rounded(sum(exact_totals.values()) / len(completed)))
            if completed
            else None,
            averages={
                str(c.pk): numeric(
                    rounded(
                        sum(Decimal(values_by_user[pk][c.pk]) for pk in completed)
                        / len(completed)
                    )
                )
                for c, *_ in specifications
                if completed
            },
            contributions={
                str(c.pk): numeric(
                    rounded(
                        sum(contributions[pk][c.pk] for pk in completed) / len(completed)
                    )
                )
                for c, *_ in specifications
                if completed
            },
            maximum=100.0,
            has_numeric_criteria=True,
        )
    numeric_criteria = [c for c in criteria if c.type in ("int", "float")]
    evaluations = {}
    for user_id, values in values_by_user.items():
        complete = complete_values(criteria, values)
        total = (
            sum(Decimal(values[c.pk]) for c in numeric_criteria)
            if complete and numeric_criteria
            else None
        )
        evaluations[user_id] = dict(complete=complete, total=numeric(total))
    completed = [pk for pk, row in evaluations.items() if row["complete"]]
    score = (
        rounded(
            sum(Decimal(str(evaluations[pk]["total"])) for pk in completed)
            / len(completed)
        )
        if completed and numeric_criteria
        else None
    )
    averages = {
        str(c.pk): numeric(
            rounded(
                sum(Decimal(values_by_user[pk][c.pk]) for pk in completed)
                / len(completed)
            )
        )
        for c in numeric_criteria
        if completed
    }
    maximum = (
        sum(Decimal(str(c.max_value)) for c in numeric_criteria)
        if numeric_criteria and all(c.max_value is not None for c in numeric_criteria)
        else None
    )
    return dict(
        evaluations=evaluations,
        completed=len(completed),
        score=numeric(score),
        averages=averages,
        maximum=numeric(maximum),
        has_numeric_criteria=bool(numeric_criteria),
        contributions={},
    )


def assign_places(rows, identity_key):
    ready = sorted(
        [row for row in rows if row["ready"]],
        key=lambda row: (-row["score"], row["name"].lower(), row[identity_key]),
    )
    last_score, place = None, 0
    for index, row in enumerate(ready, 1):
        if row["score"] != last_score:
            place = index
        row["place"] = place
        last_score = row["score"]
