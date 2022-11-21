from rest_framework import serializers


class CustomListField(serializers.ListField):
    def to_representation(self, data):
        return [value.strip() for value in data.split(",") if value.strip()]

    def to_internal_value(self, data):
        return ",".join(data)
