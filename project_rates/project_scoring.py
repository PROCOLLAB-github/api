def project_scoring_blocker(
    program,
    *,
    now,
    has_criteria,
    submitted,
    own_team,
    is_organizer,
    rated_count,
    has_own_scores,
):
    """Explain why an expert cannot submit or change an assessment in the workspace."""
    managed = program.required_evaluators is not None
    if program.datetime_evaluation_ends and now > program.datetime_evaluation_ends:
        return "Срок оценивания завершен"
    if not has_criteria:
        return "Критерии не настроены"
    if (managed or program.is_competitive) and not submitted:
        return "Проект еще не сдан"
    if (managed or is_organizer) and own_team:
        return "Нельзя оценивать проект своей команды"
    if (
        not managed
        and program.max_project_rates
        and rated_count >= program.max_project_rates
    ):
        if not has_own_scores:
            return "Лимит оценок достигнут"
    return None
