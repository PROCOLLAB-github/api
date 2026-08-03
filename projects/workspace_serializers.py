from rest_framework import serializers

from projects.models import Project


PROJECT_WORKSPACE_EDITABLE_FIELDS = frozenset(
    {
        "name",
        "description",
        "region",
        "actuality",
        "problem",
        "target_audience",
        "implementation_deadline",
        "trl",
        "presentation_address",
        "image_address",
        "cover_image_address",
        "draft",
        "is_public",
    }
)


class ProjectWorkspaceUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    avatar = serializers.URLField(allow_blank=True, allow_null=True)


class ProjectWorkspaceCollaboratorSerializer(serializers.Serializer):
    user = ProjectWorkspaceUserSerializer()
    role = serializers.CharField(allow_blank=True, allow_null=True)
    specialization = serializers.CharField(allow_blank=True, allow_null=True)


class ProjectActivitySerializer(serializers.Serializer):
    id = serializers.IntegerField(source="program_id")
    name = serializers.CharField(source="program.name")
    application_id = serializers.IntegerField(source="id")
    application_status = serializers.CharField(source="status")


class ProjectWorkspaceListSerializer(serializers.ModelSerializer):
    short_description = serializers.SerializerMethodField()
    current_user_role = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_use_in_application = serializers.SerializerMethodField()
    activities = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = (
            "id",
            "name",
            "short_description",
            "image_address",
            "cover_image_address",
            "draft",
            "is_public",
            "current_user_role",
            "can_edit",
            "can_use_in_application",
            "activities",
            "datetime_updated",
        )

    def get_short_description(self, project):
        return project.get_short_description()

    def get_current_user_role(self, project):
        user = self.context["request"].user
        if project.leader_id == user.pk:
            return "leader"
        collaborations = getattr(project, "_current_user_collaborations", ())
        return "collaborator" if collaborations else None

    def get_can_edit(self, project):
        user = self.context["request"].user
        return bool(user.is_staff or user.is_superuser or project.leader_id == user.pk)

    def get_can_use_in_application(self, project):
        return project.leader_id == self.context["request"].user.pk

    def get_activities(self, project):
        applications = getattr(project, "_workspace_applications", ())
        return ProjectActivitySerializer(applications, many=True).data


class ProjectWorkspaceDetailSerializer(ProjectWorkspaceListSerializer):
    leader = ProjectWorkspaceUserSerializer(read_only=True)
    collaborators = serializers.SerializerMethodField()
    links = serializers.SerializerMethodField()
    industry = serializers.SerializerMethodField()

    class Meta(ProjectWorkspaceListSerializer.Meta):
        fields = ProjectWorkspaceListSerializer.Meta.fields + (
            "description",
            "region",
            "actuality",
            "problem",
            "target_audience",
            "implementation_deadline",
            "trl",
            "presentation_address",
            "leader",
            "collaborators",
            "links",
            "industry",
            "datetime_created",
        )

    def get_collaborators(self, project):
        collaborators = getattr(project, "_workspace_collaborators", ())
        return ProjectWorkspaceCollaboratorSerializer(collaborators, many=True).data

    def get_links(self, project):
        return [item.link for item in project.links.all()]

    def get_industry(self, project):
        if project.industry is None:
            return None
        return {"id": project.industry_id, "name": project.industry.name}


class ProjectWorkspaceUpdateSerializer(serializers.ModelSerializer):
    editable_fields = PROJECT_WORKSPACE_EDITABLE_FIELDS

    class Meta:
        model = Project
        fields = tuple(sorted(PROJECT_WORKSPACE_EDITABLE_FIELDS))
        extra_kwargs = {
            "name": {"allow_blank": False, "allow_null": False},
            "description": {"allow_blank": True, "allow_null": True},
        }

    def validate(self, attrs):
        unsupported = set(self.initial_data).difference(self.editable_fields)
        if unsupported:
            raise serializers.ValidationError(
                {
                    field: "Это поле нельзя изменить через API рабочего пространства."
                    for field in sorted(unsupported)
                }
            )
        return attrs
