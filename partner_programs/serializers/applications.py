from rest_framework import serializers

from partner_programs.models import Application
from projects.models import Project


class ApplicationSerializer(serializers.ModelSerializer):
    project = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(),
        allow_null=True,
        required=False,
    )
    project_id = serializers.PrimaryKeyRelatedField(
        source="project",
        queryset=Project.objects.all(),
        allow_null=True,
        required=False,
        write_only=True,
    )

    immutable_input_fields = frozenset(
        {
            "id",
            "program",
            "user",
            "created_by",
            "status",
            "submitted_at",
            "approved_at",
            "rejected_at",
            "withdrawn_at",
            "created_at",
            "updated_at",
        }
    )

    class Meta:
        model = Application
        fields = (
            "id",
            "program",
            "user",
            "created_by",
            "status",
            "form_data",
            "project",
            "project_id",
            "submitted_at",
            "approved_at",
            "rejected_at",
            "withdrawn_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "program",
            "user",
            "created_by",
            "status",
            "submitted_at",
            "approved_at",
            "rejected_at",
            "withdrawn_at",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "form_data": {"required": False},
        }

    def validate(self, attrs):
        supplied_immutable_fields = self.immutable_input_fields.intersection(
            self.initial_data
        )
        if supplied_immutable_fields:
            raise serializers.ValidationError(
                {
                    field: "This field is read-only."
                    for field in sorted(supplied_immutable_fields)
                }
            )

        if "project" in self.initial_data and "project_id" in self.initial_data:
            raise serializers.ValidationError(
                {"project": "Use either project or project_id, not both."}
            )

        if self.instance and self.instance.status != Application.STATUS_DRAFT:
            raise serializers.ValidationError(
                {"status": "Only draft applications can be updated."}
            )

        project = attrs.get("project", serializers.empty)
        if project is not serializers.empty and project is not None:
            request = self.context.get("request")
            user = getattr(request, "user", None)
            if not user or not user.is_authenticated or project.leader_id != user.pk:
                raise serializers.ValidationError(
                    {"project": "You can only use a project that you lead."}
                )

        return attrs
