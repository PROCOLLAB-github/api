from rest_framework import serializers

from news.models import News


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
        ]
