from rest_framework import serializers

from news.models import News, NewsTag


class NewsSerializer(serializers.ModelSerializer):
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
            "tags",
        ]


class NewsTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsTag
        fields = ["id", "name", "description"]
