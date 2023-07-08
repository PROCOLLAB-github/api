from rest_framework import serializers

from core.services import get_likes_count, get_views_count, get_links
from partner_programs.models import PartnerProgram


class PartnerProgramListSerializer(serializers.ModelSerializer):
    """Serializer for PartnerProgram model for list view."""

    likes_count = serializers.SerializerMethodField(method_name="count_likes")
    views_count = serializers.SerializerMethodField(method_name="count_views")
    links = serializers.SerializerMethodField(method_name="get_links")

    def count_likes(self, program):
        return get_likes_count(program)

    def count_views(self, program):
        return get_views_count(program)

    def get_links(self, program):
        # FIXME
        # TODO: add caching here at least every 5 minutes, otherwise this will be heavy load
        return get_links(program)

    class Meta:
        model = PartnerProgram
        fields = (
            "id",
            "name",
            "tag",
            "links",
            "description",
            "city",
            "links",
            "image_address",
            "advertisement_image_address",
            "users",
            "datetime_registration_ends",
            "datetime_started",
            "datetime_finished",
            "views_count",
            "likes_count",
        )


class PartnerProgramDetailSerializer(serializers.ModelSerializer):
    """Serializer for PartnerProgram model for detail view."""

    likes_count = serializers.SerializerMethodField(method_name="count_likes")
    views_count = serializers.SerializerMethodField(method_name="count_views")
    links = serializers.SerializerMethodField(method_name="get_links")

    def count_likes(self, program):
        return get_likes_count(program)

    def count_views(self, program):
        return get_views_count(program)

    def get_links(self, program):
        # FIXME
        # TODO: add caching here at least every 5 minutes, otherwise this will be heavy load
        return get_links(program)

    class Meta:
        model = PartnerProgram
        fields = (
            "id",
            "name",
            "tag",
            "links",
            "description",
            "city",
            "links",
            "image_address",
            "cover_image_address",
            "advertisement_image_address",
            "presentation_address",
            "data_schema",
            "users",
            "datetime_registration_ends",
            "datetime_started",
            "datetime_finished",
            "datetime_created",
            "datetime_updated",
            "views_count",
            "likes_count",
        )
