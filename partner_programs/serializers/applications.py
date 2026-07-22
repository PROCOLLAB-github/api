from rest_framework import serializers

from partner_programs.models import Application, Team
from partner_programs.serializers.teams import ApplicationTeamSummarySerializer
from projects.models import Project


class ApplicationSerializer(serializers.ModelSerializer):
    team = serializers.SerializerMethodField()
    team_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        write_only=True,
    )
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
            "team",
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
            "participation_mode",
            "team",
            "team_name",
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
            "participation_mode": {"required": False},
        }

    def get_team(self, application: Application):
        try:
            team = application.team
        except Team.DoesNotExist:
            return None
        return ApplicationTeamSummarySerializer(
            team,
            context=self.context,
        ).data

    def update(self, instance, validated_data):
        # Формат и Team изменяет только domain service; serializer сохраняет
        # остальные редактируемые поля в общей транзакции view.
        validated_data.pop("participation_mode", None)
        validated_data.pop("team_name", None)
        return super().update(instance, validated_data)

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
            if (
                not user
                or not user.is_authenticated
                or (
                    project.leader_id != user.pk
                    and not (user.is_staff or user.is_superuser)
                )
            ):
                raise serializers.ValidationError(
                    {"project": "You can only use a project that you lead."}
                )

        return attrs
