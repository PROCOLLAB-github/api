"""Opt-in контракт менеджера, отдельный от прежнего сериализатора проектов."""

from rest_framework import serializers

from .project_analytics_attention import participant_name


def case_analytics_requested(params):
    if not {"view", "case_scope", "case_name"}.intersection(params):
        return False
    if params.get("view") != "case_analytics":
        raise serializers.ValidationError({"view": "Укажите view=case_analytics."})
    return True


class ProjectCaseQuerySerializer(serializers.Serializer):
    view = serializers.ChoiceField(choices=("case_analytics",))
    case_scope = serializers.ChoiceField(choices=("all", "selected", "without_case"))
    case_name = serializers.CharField(required=False, trim_whitespace=False)

    def to_internal_value(self, data):
        errors = {
            key: "Параметр не поддерживается в этом режиме."
            for key in set(data) - set(self.fields)
        }
        if hasattr(data, "getlist"):
            for key in data:
                if len(data.getlist(key)) != 1:
                    errors[key] = "Укажите параметр только один раз."
        if errors:
            raise serializers.ValidationError(errors)
        # DRF считает QueryDict HTML-формой: пустой integer иначе становится
        # отсутствующим полем и незаметно получает default.
        return super().to_internal_value({key: data[key] for key in data})

    def validate(self, attrs):
        if attrs["case_scope"] == "selected":
            if attrs.get("case_name") not in self.context["case_options"]:
                raise serializers.ValidationError(
                    {"case_name": "Выберите точный текущий вариант кейса."}
                )
        elif "case_name" in attrs:
            raise serializers.ValidationError(
                {"case_name": "Название допустимо только для case_scope=selected."}
            )
        return attrs


class ProjectCaseListQuerySerializer(ProjectCaseQuerySerializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=25)
    offset = serializers.IntegerField(min_value=0, default=0)
    search = serializers.CharField(allow_blank=True, default="", trim_whitespace=True)


class CaseProjectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    presentation_address = serializers.CharField(allow_null=True, allow_blank=True)
    region = serializers.CharField(allow_null=True, allow_blank=True)


class CaseLeaderSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(source="pk")
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, user):
        return participant_name(user.pk, user.first_name, user.last_name)


class ProjectCaseRowSerializer(serializers.Serializer):
    program_project_id = serializers.IntegerField(source="pk")
    project = CaseProjectSerializer()
    case = serializers.SerializerMethodField()
    leader = CaseLeaderSerializer(source="project.leader", allow_null=True)
    team_size = serializers.IntegerField()
    linked_at = serializers.DateTimeField(source="datetime_created")
    submitted = serializers.BooleanField()
    submitted_at = serializers.SerializerMethodField()

    def get_case(self, link):
        return {
            "kind": "selected" if link.case_name is not None else "without_case",
            "name": link.case_name,
        }

    def get_submitted_at(self, link):
        if not link.submitted or link.datetime_submitted is None:
            return None
        return serializers.DateTimeField().to_representation(link.datetime_submitted)
