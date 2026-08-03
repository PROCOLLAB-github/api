from django.db import transaction
from rest_framework import serializers

from projects.models import Project, ProjectLink


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
        "industry",
        "links",
        "draft",
        "is_public",
    }
)

PROJECT_PUBLICATION_REQUIRED_FIELDS = {
    "name": "Укажите название проекта.",
    "region": "Укажите регион.",
    "industry": "Выберите отрасль.",
    "description": "Добавьте описание проекта.",
    "problem": "Опишите проблему.",
    "target_audience": "Опишите целевую аудиторию.",
    "cover_image_address": "Загрузите обложку проекта.",
}


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
    links = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        allow_empty=True,
        write_only=True,
    )

    class Meta:
        model = Project
        fields = tuple(sorted(PROJECT_WORKSPACE_EDITABLE_FIELDS))
        extra_kwargs = {
            "name": {"allow_blank": False, "allow_null": False},
            "description": {"allow_blank": True, "allow_null": True},
        }

    def _get_resulting_value(self, attrs, field):
        """Возвращает значение поля после применения частичного обновления."""
        if field in attrs:
            return attrs[field]
        return getattr(self.instance, field)

    def _requires_publication_validation(self, attrs):
        """Определяет, переводит ли запрос Project в публикуемое состояние.

        Legacy Project может уже иметь сочетание draft=true и is_public=true,
        поэтому обычное редактирование такого объекта не считаем публикацией.
        Явное включение публичности или снятие флага черновика всегда требует
        заполненного проекта, как и изменение уже опубликованного Project.
        """
        resulting_draft = self._get_resulting_value(attrs, "draft")
        resulting_is_public = self._get_resulting_value(attrs, "is_public")
        return (
            ("draft" in attrs and resulting_draft is False)
            or ("is_public" in attrs and resulting_is_public is True)
            or (resulting_draft is False and resulting_is_public is True)
        )

    def validate(self, attrs):
        unsupported = set(self.initial_data).difference(self.editable_fields)
        if unsupported:
            raise serializers.ValidationError(
                {
                    field: "Это поле нельзя изменить через API рабочего пространства."
                    for field in sorted(unsupported)
                }
            )

        if self._requires_publication_validation(attrs):
            errors = {}
            for field, message in PROJECT_PUBLICATION_REQUIRED_FIELDS.items():
                value = self._get_resulting_value(attrs, field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    errors[field] = message
            if errors:
                raise serializers.ValidationError(errors)
        return attrs

    def validate_links(self, links):
        """Удаляет дубликаты ссылок, сохраняя пользовательский порядок."""
        return list(dict.fromkeys(links))

    @transaction.atomic
    def update(self, instance, validated_data):
        """Атомарно обновляет Project и его отдельные строки ProjectLink."""
        links = validated_data.pop("links", None)
        project = super().update(instance, validated_data)
        if links is not None:
            ProjectLink.objects.filter(project=project).delete()
            ProjectLink.objects.bulk_create(
                [ProjectLink(project=project, link=link) for link in links]
            )
        return project


class ProjectWorkspaceCreateSerializer(serializers.Serializer):
    """Создает пустой приватный черновик без клиентских полей владения."""

    def validate(self, attrs):
        if self.initial_data:
            raise serializers.ValidationError(
                {
                    field: "Поле нельзя передавать при создании черновика."
                    for field in sorted(self.initial_data)
                }
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # Отдельный React-контур явно создает private draft; legacy POST /projects/
        # сохраняет прежний контракт и model default is_public.
        return Project.objects.create(
            leader=self.context["request"].user,
            draft=True,
            is_public=False,
        )
