from rest_framework import serializers
from feed import constants


class FeedItemSerializer(serializers.Serializer):
    type_model = serializers.ChoiceField(choices=constants.FeedItemType, required=True)
    content = serializers.JSONField(required=True)


class PagTestSerializer(serializers.Serializer):
    def to_representation(self, instance):
        return constants.FEED_SERIALIZER_MAPPING[instance.__class__.__name__](
            instance=instance
        )
