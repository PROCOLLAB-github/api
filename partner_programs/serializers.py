from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.services import get_likes_count, get_links, get_views_count, is_fan
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramMaterial,
)

User = get_user_model()


class PartnerProgramListSerializer(serializers.ModelSerializer):
    """Serializer for PartnerProgram model for list view."""

    likes_count = serializers.SerializerMethodField(method_name="count_likes")
    views_count = serializers.SerializerMethodField(method_name="count_views")
    short_description = serializers.SerializerMethodField(
        method_name="get_short_description"
    )
    is_user_liked = serializers.SerializerMethodField(method_name="get_is_user_liked")

    def count_likes(self, program):
        return get_likes_count(program)

    def count_views(self, program):
        return get_views_count(program)

    def get_short_description(self, program):
        return program.description[:125]

    def get_is_user_liked(self, obj):
        # fixme: copy-paste in every serializer...
        user = self.context.get("user")
        if user:
            return is_fan(obj, user)
        return False

    class Meta:
        model = PartnerProgram
        fields = (
            "id",
            "name",
            "image_address",
            "short_description",
            "datetime_registration_ends",
            "datetime_started",
            "datetime_finished",
            "views_count",
            "likes_count",
            "is_user_liked",
        )


class PartnerProgramBaseSerializerMixin(serializers.ModelSerializer):
    """
    Базовый миксин для сериализаторов PartnerProgram,
    включает общие поля: materials и is_user_manager.
    """

    materials = serializers.SerializerMethodField()
    is_user_manager = serializers.SerializerMethodField()

    def get_materials(self, program: PartnerProgram):
        materials = program.materials.all()
        return PartnerProgramMaterialSerializer(materials, many=True).data

    def get_is_user_manager(self, program: PartnerProgram) -> bool:
        user = self.context.get("user")
        return bool(user and program.is_manager(user))

    class Meta:
        abstract = True


class PartnerProgramForMemberSerializer(PartnerProgramBaseSerializerMixin):
    """Serializer for PartnerProgram model for member of this program"""

    views_count = serializers.SerializerMethodField(method_name="count_views")
    links = serializers.SerializerMethodField(method_name="get_links")
    is_user_manager = serializers.SerializerMethodField(method_name="get_is_user_manager")

    def count_views(self, program):
        return get_views_count(program)

    def get_links(self, program):
        # TODO: add caching here at least every 5 minutes, otherwise this will be heavy load
        # fixme: create LinksSerializer mb?
        return [link.link for link in get_links(program)]

    def get_is_user_liked(self, obj):
        # fixme: copy-paste in every serializer...
        user = self.context.get("user")
        if user:
            return is_fan(obj, user)
        return False

    class Meta:
        model = PartnerProgram
        fields = (
            "id",
            "name",
            "tag",
            "description",
            "city",
            "links",
            "materials",
            "image_address",
            "cover_image_address",
            "presentation_address",
            "views_count",
            "datetime_registration_ends",
            "is_user_manager",
        )


class PartnerProgramForUnregisteredUserSerializer(PartnerProgramBaseSerializerMixin):
    """Serializer for PartnerProgram model for unregistered users in the program"""

    class Meta:
        model = PartnerProgram
        fields = (
            "id",
            "name",
            "tag",
            "city",
            "materials",
            "image_address",
            "cover_image_address",
            "advertisement_image_address",
            "presentation_address",
            "datetime_registration_ends",
            "is_user_manager",
        )


class PartnerProgramNewUserSerializer(serializers.ModelSerializer):
    """Serializer for creating new user and register him to program."""

    program_data = serializers.JSONField(required=True)

    class Meta:
        model = User
        fields = (
            "email",
            "password",
            "first_name",
            "last_name",
            "patronymic",
            "program_data",
        )


class PartnerProgramUserSerializer(serializers.Serializer):
    program_data = serializers.JSONField(required=True)


class PartnerProgramDataSchemaSerializer(serializers.Serializer):
    data_schema = serializers.JSONField(required=True)


class UserProgramsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartnerProgram
        fields = [
            "id",
            "name",
            "tag",
        ]


class PartnerProgramMaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartnerProgramMaterial
        fields = ("title", "url")


class PartnerProgramFieldValueSerializer(serializers.ModelSerializer):
    field_name = serializers.CharField(source="field.name")
    value = serializers.SerializerMethodField()

    class Meta:
        model = PartnerProgramFieldValue
        fields = [
            "field_name",
            "value",
        ]

    def get_value(self, obj):
        if obj.field.field_type == "file":
            return obj.value_file.link if obj.value_file else None
        return obj.value_text


class PartnerProgramFieldSerializer(serializers.ModelSerializer):
    options = serializers.SerializerMethodField()

    class Meta:
        model = PartnerProgramField
        fields = [
            "id",
            "name",
            "label",
            "field_type",
            "is_required",
            "show_filter",
            "help_text",
            "options",
        ]

    def get_options(self, obj):
        return obj.get_options_list()


class ProgramProjectFilterRequestSerializer(serializers.Serializer):
    filters = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        required=False,
        help_text="Словарь: ключ = PartnerProgramField.name, значение = список выбранных опций",
    )
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(
        required=False, default=20, min_value=1, max_value=200
    )
    MAX_FILTERS = 3

    def validate_filters(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "Поле filters должно быть объектом (словарём ключ-значение)"
            )

        if len(value) > self.MAX_FILTERS:
            raise serializers.ValidationError(
                f"Можно передать не более {self.MAX_FILTERS} фильтров."
            )

        cleaned: dict = {}
        for key, raw_values in value.items():
            if not isinstance(key, str) or not key.strip():
                raise serializers.ValidationError(
                    f"Ключи фильтров должны быть непустыми строками. Некорректный ключ: {key}"
                )

            if isinstance(raw_values, list):
                normalized_values = [
                    str(item).strip() for item in raw_values if str(item).strip() != ""
                ]
            else:
                normalized_values = (
                    [str(raw_values).strip()] if str(raw_values).strip() != "" else []
                )

            if not normalized_values:
                continue

            cleaned[key.strip()] = normalized_values

        return cleaned
