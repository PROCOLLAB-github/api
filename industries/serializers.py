from django_stubs_ext.db.models import TypedModelMeta
from rest_framework import serializers

from industries.models import Industry


class IndustrySerializer(serializers.ModelSerializer):
    class Meta(TypedModelMeta):
        model = Industry
        fields = ["id", "name", "datetime_created"]
