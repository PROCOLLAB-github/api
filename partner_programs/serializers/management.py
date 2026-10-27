"""Контракты панели организатора; поля ролей и жизненного цикла не редактируются."""

import math
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


class ImageFramingField(serializers.JSONField):
    """Full framing document; empty object restores legacy center/100% defaults."""

    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        if not isinstance(data, dict):
            raise serializers.ValidationError("Укажите объект настроек кадра.")
        if not data:
            return {}
        if set(data) != {"cover", "mobile_cover", "logo"}:
            raise serializers.ValidationError(
                "Укажите только cover, mobile_cover и logo."
            )
        for frame in data.values():
            if not isinstance(frame, dict) or set(frame) != {"x", "y", "zoom"}:
                raise serializers.ValidationError(
                    "Каждый кадр должен содержать x, y, zoom."
                )
            for key, maximum in (("x", 100), ("y", 100), ("zoom", 3)):
                value = frame[key]
                minimum = 1 if key == "zoom" else 0
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not minimum <= value <= maximum
                    or not math.isfinite(value)
                ):
                    raise serializers.ValidationError(
                        f"{key}: укажите число от {minimum} до {maximum}."
                    )
        return data


class ManagementListQuery(StrictFieldsMixin, serializers.Serializer):
    search = serializers.CharField(
        required=False, allow_blank=True, max_length=200, default=""
    )
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)


class ManagementParticipantQuery(ManagementListQuery):
    region_scope = serializers.ChoiceField(
        choices=("all", "selected", "without_region"), default="all"
    )
    region = serializers.CharField(required=False, max_length=255)
    activity = serializers.ChoiceField(
        choices=("all", "period", "active", "inactive", "never"), default="all"
    )
    order = serializers.ChoiceField(
        choices=("registration", "activity_asc", "activity_desc"), default="activity_desc"
    )
    activity_from = serializers.DateField(required=False)
    activity_to = serializers.DateField(required=False)

    def validate(self, attrs):
        if attrs["region_scope"] == "selected" and not attrs.get("region"):
            raise serializers.ValidationError({"region": "Выберите регион."})
        if attrs["region_scope"] != "selected" and attrs.get("region"):
            raise serializers.ValidationError(
                {"region": "Регион задан без selected scope."}
            )
        start, end = attrs.get("activity_from"), attrs.get("activity_to")
        if attrs["activity"] == "period":
            if not (start or end):
                raise serializers.ValidationError(
                    {"activity_from": "Укажите начало или конец периода."}
                )
            if start and end and start > end:
                raise serializers.ValidationError(
                    {"activity_to": "Конец периода раньше начала."}
                )
        elif start or end:
            raise serializers.ValidationError(
                {"activity": "Даты доступны только для периода."}
            )
        return attrs


class ManagementProjectQuery(ManagementListQuery):
    evaluation = serializers.ChoiceField(
        choices=("all", "evaluated", "not_evaluated"), default="all"
    )
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


class ManagementIdsWrite(StrictFieldsMixin, serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=10000
    )

    def validate_ids(self, values):
        return sorted(set(values))


class ManagementRemovalWrite(ManagementIdsWrite):
    preview_token = serializers.CharField(max_length=200000)
    confirmation_version = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if attrs.get("confirmation_version") != 2:
            raise serializers.ValidationError(
                {
                    "detail": "Обновите страницу и заново подтвердите удаление участников из команд заявок."
                }
            )
        return attrs


class ManagementProjectActionWrite(ManagementIdsWrite):
    action = serializers.ChoiceField(choices=("change_case", "detach", "submit"))
    case_name = serializers.CharField(
        required=False, max_length=1000, trim_whitespace=False
    )

    def to_internal_value(self, data):
        from collections.abc import Mapping

        if not isinstance(data, Mapping):
            raise serializers.ValidationError(
                {"detail": "Ожидается объект с параметрами действия."}
            )
        return super().to_internal_value(data)

    def validate(self, attrs):
        if attrs["action"] != "submit" and len(attrs["ids"]) != 1:
            raise serializers.ValidationError({"ids": "Выберите один проект."})
        if attrs["action"] == "change_case" and not attrs.get("case_name"):
            raise serializers.ValidationError({"case_name": "Выберите кейс."})
        if attrs["action"] != "change_case" and "case_name" in attrs:
            raise serializers.ValidationError(
                {"case_name": "Кейс не используется в этом действии."}
            )
        return attrs


class ManagementProjectActionApply(ManagementProjectActionWrite):
    preview_token = serializers.CharField(max_length=200000)


BASIC_FIELDS = (
    "name",
    "city",
    "tag",
    "description",
    "image_address",
    "cover_image_address",
    "mobile_cover_image_address",
    "image_framing",
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
    image_framing = ImageFramingField(required=False)
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
            if (
                name
                in ("datetime_started", "datetime_finished", "datetime_registration_ends")
                and self.instance is not None
                and not self.instance.draft
            ):
                fields[name].allow_null = False
            if name.endswith("_address") or name == "registration_link":
                fields[name] = HttpURLField(
                    required=False, allow_null=True, allow_blank=True
                )
        fields["expected_updated_at"].required = True
        return fields

    def validate(self, attrs):
        editable = BASIC_FIELDS if self.context["section"] == "basic" else DATE_FIELDS
        if not any(key in attrs for key in editable):
            raise serializers.ValidationError("Нет измененных полей.")
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
