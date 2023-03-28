from rest_framework.serializers import ModelSerializer

from files.models import UserFile


class UserFileSerializer(ModelSerializer):
    class Meta:
        model = UserFile
        fields = [
            "name",
            "extension",
            "size",
            "link",
            "user",
            "datetime_uploaded",
        ]
