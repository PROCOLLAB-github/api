from rest_framework import serializers

from .models import CustomUser


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            "id",
            "user_type",
            "email",
            "first_name",
            "last_name",
            "patronymic",
            "avatar",
            "city",
            "password",
        ]

    def create(self, validated_data):
        user = CustomUser(**validated_data)
        print("qwer", validated_data)
        user.set_password(validated_data["password"])
        user.save()

        return user


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyEmailSerializer(serializers.Serializer):
    result = serializers.JSONField()


class PasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(required=True)
