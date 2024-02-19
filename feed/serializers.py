from rest_framework import serializers
from feed import constants


class FeedItemSerializer(serializers.Serializer):
    type_model = serializers.ChoiceField(choices=constants.FeedItemType, required=True)
    content = serializers.JSONField(required=True)
