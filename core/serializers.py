from rest_framework import serializers

from .models import SkillToObject, SkillCategory, Skill


class SetLikedSerializer(serializers.Serializer):
    is_liked = serializers.BooleanField()


class SetViewedSerializer(serializers.Serialize[SkillCategory]):
    is_viewed = serializers.BooleanField()


class SkillCategorySerializer(serializers.ModelSerializer[SkillCategory]):
    class Meta:
        model = SkillCategory
        fields = [
            "id",
            "name",
        ]


class SkillSerializer(serializers.ModelSerializer[Skill]):
    category = SkillCategorySerializer()

    class Meta:
        model = Skill
        fields = ["id", "name", "category"]


class SkillToObjectSerializer(serializers.ModelSerializer[SkillToObject]):
    id = serializers.IntegerField(source="skill.id")
    name = serializers.CharField(source="skill.name")
    category = SkillCategorySerializer(source="skill.category")

    class Meta:
        model = SkillToObject
        fields = ["id", "name", "category"]


class SkillsSerializer(serializers.ModelSerializer[SkillCategory]):
    skills = SkillSerializer(many=True)

    class Meta:
        model = SkillCategory
        fields = ["id", "name", "skills"]
