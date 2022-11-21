from rest_framework import serializers


class CustomListField(serializers.ListField):
    def to_representation(self, data):
        return [i.strip() for i in data.split(",")]
