from rest_framework import serializers

from partner_programs.models import Submission


class SubmissionSerializer(serializers.ModelSerializer):
    create_fields = frozenset(
        {
            "title",
            "description",
            "form_data",
            "links",
            "stage_key",
            "version",
        }
    )
    update_fields = frozenset(
        {
            "title",
            "description",
            "form_data",
            "links",
        }
    )

    class Meta:
        model = Submission
        fields = (
            "id",
            "application",
            "program",
            "submitted_by",
            "title",
            "description",
            "form_data",
            "links",
            "status",
            "stage_key",
            "version",
            "submitted_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "application",
            "program",
            "submitted_by",
            "status",
            "submitted_at",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "description": {"required": False},
            "form_data": {"required": False},
            "links": {"required": False},
            "stage_key": {"required": False},
            "version": {"required": False, "min_value": 1},
        }

    def validate(self, attrs):
        allowed_fields = self.update_fields if self.instance else self.create_fields
        unsupported_fields = set(self.initial_data).difference(allowed_fields)
        if unsupported_fields:
            raise serializers.ValidationError(
                {
                    field: "This field is read-only."
                    for field in sorted(unsupported_fields)
                }
            )

        if self.instance and not self.instance.can_edit:
            raise serializers.ValidationError(
                {"status": "Only draft or returned submissions can be updated."}
            )

        return attrs
