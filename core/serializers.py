from rest_framework import serializers


class SetLikedSerializer(serializers.Serializer):
    is_liked = serializers.BooleanField()


class SetViewedSerializer(serializers.Serializer):
    is_viewed = serializers.BooleanField()
