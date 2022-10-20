from rest_framework import serializers

from .models import CustomUser


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            "email",
            "first_name",
            "last_name",
            "password",
            "is_active",
            "patronymic",
            "birthday",
            "avatar",
            "key_skills",
            "useful_to_project",
            "about_me",
            "status",
            "speciality",
            "city",
            "region",
            "organization",
        ]

    def create(self, validated_data):
        user = CustomUser(**validated_data)
        user.set_password(validated_data["password"])
        user.save()

        return user
