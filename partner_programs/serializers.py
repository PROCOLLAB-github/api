from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.services import get_likes_count, get_links, get_views_count, is_fan
from partner_programs.models import PartnerProgram

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
        return program.description[:100]

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


class PartnerProgramForMemberSerializer(serializers.ModelSerializer):
    """Serializer for PartnerProgram model for member of this program"""

    views_count = serializers.SerializerMethodField(method_name="count_views")
    links = serializers.SerializerMethodField(method_name="get_links")

    def count_views(self, program):
        return get_views_count(program)

    def get_links(self, program):
        # FIXME
        # TODO: add caching here at least every 5 minutes, otherwise this will be heavy load
        return get_links(program)

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
            "image_address",
            "cover_image_address",
            "presentation_address",
            "views_count",
        )


class PartnerProgramForUnregisteredUserSerializer(serializers.ModelSerializer):
    """Serializer for PartnerProgram model for unregistered users in the program"""

    class Meta:
        model = PartnerProgram
        fields = (
            "id",
            "name",
            "tag",
            "city",
            "image_address",
            "cover_image_address",
            "advertisement_image_address",
            "presentation_address",
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
