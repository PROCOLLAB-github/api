from rest_framework import serializers

from news.models import News


class NewsDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = News
        fields = [
            "id",
            "title",
            "text",
            "short_text",
            "cover_url",
            "datetime_created",
            "datetime_updated",
        ]


class NewsListSerializer(serializers.ModelSerializer):
    class Meta:
        model = News
        fields = [
            "id",
            "title",
            "short_text",
            "cover_url",
            "datetime_created",
        ]
