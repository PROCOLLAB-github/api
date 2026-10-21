from rest_framework import serializers

MAX_SELECTION = 10000
CATEGORIES = (
    "participants-without-visit",
    "participants-without-team",
    "projects-awaiting-evaluation",
)


class AttentionSelectionSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=("selected", "all"))
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        max_length=MAX_SELECTION,
        default=list,
    )
    excluded_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        max_length=MAX_SELECTION,
        default=list,
    )

    def validate(self, data):
        if data["mode"] == "all" and data["ids"]:
            raise serializers.ValidationError(
                "Для всех найденных используйте только исключения."
            )
        if data["mode"] == "selected" and (not data["ids"] or data["excluded_ids"]):
            raise serializers.ValidationError("Выберите хотя бы одну строку.")
        return data


class AttentionActionSerializer(serializers.Serializer):
    search = serializers.CharField(
        max_length=200, allow_blank=True, default="", trim_whitespace=True
    )
    selection = AttentionSelectionSerializer()


class AttentionConfirmationSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=1000000)
