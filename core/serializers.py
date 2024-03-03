from rest_framework import serializers
from .models import SkillToObject, SkillCategory


class SetLikedSerializer(serializers.Serializer):
    is_liked = serializers.BooleanField()


class SetViewedSerializer(serializers.Serializer):
    is_viewed = serializers.BooleanField()


class SkillCategorySerializer(serializers.ModelSerializer[SkillCategory]):
    class Meta:
        model = SkillCategory
        fields = [
            "id",
            "name",
        ]


class SkillSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="skill.id")
    name = serializers.CharField(source="skill.name")
    category = SkillCategorySerializer(source="skill.category")

    class Meta:
        model = SkillToObject
        fields = ["id", "name", "category"]
