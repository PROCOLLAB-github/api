"""Контракты панели организатора; поля ролей и жизненного цикла не редактируются."""

from urllib.parse import urlsplit

from rest_framework import serializers

from files.models import UserFile
from partner_programs.models import PartnerProgram


class StrictFieldsMixin:
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {key: "Поле не поддерживается." for key in sorted(unknown)}
            )
        return super().to_internal_value(data)


class HttpURLField(serializers.URLField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if urlsplit(value).scheme.lower() not in ("http", "https"):
            raise serializers.ValidationError("Укажите ссылку http или https.")
        return value


class ManagementListQuery(StrictFieldsMixin, serializers.Serializer):
    search = serializers.CharField(
        required=False, allow_blank=True, max_length=200, default=""
    )
    limit = serializers.IntegerField(min_value=1, max_value=100, default=25)
    offset = serializers.IntegerField(min_value=0, default=0)


class ManagementProjectQuery(ManagementListQuery):
    submission = serializers.ChoiceField(
        choices=("all", "submitted", "not_submitted"), default="all"
    )
    case_scope = serializers.ChoiceField(
        choices=("all", "selected", "without_case"), default="all"
    )
    case_name = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def validate(self, attrs):
        if attrs["case_scope"] == "selected":
            if attrs.get("case_name") not in self.context["case_options"]:
                raise serializers.ValidationError(
                    {"case_name": "Выберите доступный кейс."}
                )
        elif attrs.get("case_name"):
            raise serializers.ValidationError(
                {"case_name": "Кейс задан без selected scope."}
            )
        return attrs


BASIC_FIELDS = (
    "name",
    "city",
    "tag",
    "description",
    "image_address",
    "cover_image_address",
    "advertisement_image_address",
    "registration_link",
    "presentation_address",
)
DATE_FIELDS = (
    "datetime_started",
    "datetime_registration_ends",
    "datetime_project_submission_ends",
    "datetime_evaluation_ends",
    "datetime_finished",
)


class ManagementSettingsSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    expected_updated_at = serializers.DateTimeField(write_only=True)
    confirm_reopen = serializers.BooleanField(
        write_only=True, required=False, default=False
    )

    def get_fields(self):
        fields = super().get_fields()
        allowed = BASIC_FIELDS if self.context["section"] == "basic" else DATE_FIELDS
        for name in list(fields):
            if name not in (*allowed, "expected_updated_at", "confirm_reopen"):
                del fields[name]
        for name in allowed:
            fields[name].required = False
            if name.endswith("_address") or name == "registration_link":
                fields[name] = HttpURLField(
                    required=False, allow_null=True, allow_blank=True
                )
        fields["expected_updated_at"].required = True
        return fields

    def validate(self, attrs):
        editable = BASIC_FIELDS if self.context["section"] == "basic" else DATE_FIELDS
        if not any(key in attrs for key in editable):
            raise serializers.ValidationError("Нет изменённых полей.")
        return attrs

    class Meta:
        model = PartnerProgram
        fields = (*BASIC_FIELDS, *DATE_FIELDS, "expected_updated_at", "confirm_reopen")
        extra_kwargs = {"name": {"allow_blank": False}}


class ManagementMaterialWrite(StrictFieldsMixin, serializers.Serializer):
    title = serializers.CharField(max_length=255)
    url = HttpURLField(required=False, allow_blank=True, allow_null=True, default=None)
    file = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None
    )
    expected_updated_at = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        instance = self.context.get("instance")
        if instance is not None and "expected_updated_at" not in attrs:
            raise serializers.ValidationError(
                {"expected_updated_at": "Обязательное поле."}
            )
        file_id, url = attrs.get("file"), attrs.get("url")
        if bool(file_id) == bool(url):
            raise serializers.ValidationError("Укажите файл или ссылку — один источник.")
        if file_id:
            file = UserFile.objects.filter(pk=file_id).first()
            user = self.context["user"]
            retained = instance is not None and instance.file_id == file_id
            if file is None or not (
                retained or file.user_id == user.pk or user.is_staff or user.is_superuser
            ):
                raise serializers.ValidationError({"file": "Файл недоступен."})
            attrs["file"] = file
            attrs["url"] = file.link
        else:
            attrs["file"] = None
        return attrs
