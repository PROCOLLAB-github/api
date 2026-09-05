"""Безопасные read-only контракты детализации показателей внимания программы."""

from rest_framework import serializers

from partner_programs.serializers.analytics import AssignmentProjectSerializer


def participant_name(user_id, first_name, last_name):
    """Отображаемое имя без приватных полей и нейтральная замена пустого имени."""
    name = " ".join(
        part.strip() for part in (first_name, last_name) if part and part.strip()
    )
    return name or f"Участник №{user_id}"


class ProgramAttentionQuerySerializer(serializers.Serializer):
    """Проверяет limit/offset до SQL; search применяется до выбора страницы."""

    limit = serializers.IntegerField(min_value=1, max_value=100, default=25)
    offset = serializers.IntegerField(min_value=0, default=0)
    search = serializers.CharField(allow_blank=True, default="", trim_whitespace=True)


class ProgramAttentionParticipantSerializer(serializers.Serializer):
    """Один уникальный пользователь программы, без анкеты, email и телефона."""

    user_id = serializers.IntegerField()
    full_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    registered_at = serializers.DateTimeField(allow_null=True)

    def get_full_name(self, row):
        """Имя строится только из уже выбранных публичных полей пользователя."""
        return participant_name(
            row["user_id"], row["user__first_name"], row["user__last_name"]
        )

    def get_avatar(self, row):
        """Пустой avatar унифицирован в null, без запроса пользователя."""
        return row["user__avatar"] or None

    def get_city(self, row):
        """Сохраняет фактическую географию, не нормализуя legacy-значения."""
        return row["user__city"] or None


class ProgramAttentionLeaderSerializer(serializers.Serializer):
    """Разрешённые поля руководителя; полный сериализатор User не используется."""

    user_id = serializers.IntegerField(source="id")
    full_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    def get_full_name(self, user):
        """Использует руководителя, загруженного вместе со связью проекта."""
        return participant_name(user.pk, user.first_name, user.last_name)

    def get_avatar(self, user):
        """Возвращает URL или null из уже загруженной модели."""
        return user.avatar or None


WAITING_REASONS = {
    "no_assignments": "Эксперты не назначены",
    "no_completed_evaluations": "Нет завершённых оценок",
    "partially_evaluated": "Частично оценено",
    "awaiting_first_evaluation": "Ожидает первой оценки",
}


class ProgramAttentionProjectSerializer(serializers.Serializer):
    """Одна сданная работа программы, а не строка назначения эксперта."""

    program_project_id = serializers.IntegerField(source="pk")
    project = AssignmentProjectSerializer()
    leader = ProgramAttentionLeaderSerializer(source="project.leader", allow_null=True)
    submitted_at = serializers.DateTimeField(source="datetime_submitted", allow_null=True)
    status = serializers.ChoiceField(
        choices=("awaiting_evaluation", "partially_evaluated")
    )
    reason = serializers.SerializerMethodField()
    reason_label = serializers.SerializerMethodField()
    assignments_total = serializers.IntegerField(allow_null=True)
    assignments_completed = serializers.IntegerField(allow_null=True)

    def get_reason(self, link):
        """Причина следует из общего статуса и реальных назначений, не из лимита."""
        if link.assignments_total is None:
            return "awaiting_first_evaluation"
        if link.assignments_total == 0:
            return "no_assignments"
        if link.assignments_completed == 0:
            return "no_completed_evaluations"
        return "partially_evaluated"

    def get_reason_label(self, link):
        """Контролируемая подпись не трактует отсутствие завершения как отсутствие начала."""
        return WAITING_REASONS[self.get_reason(link)]
