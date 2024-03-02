from rest_framework import serializers
from .models import SkillToObject


class SetLikedSerializer(serializers.Serializer):
    is_liked = serializers.BooleanField()


class SetViewedSerializer(serializers.Serializer):
    is_viewed = serializers.BooleanField()


class SkillSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()

    class Meta:
        model = SkillToObject
        fields = ["id", "name", "category"]

    def get_id(self, obj):
        return obj.skill.id

    def get_name(self, obj):
        return obj.skill.name

    def get_category(self, obj):
        return obj.skill.category.name
