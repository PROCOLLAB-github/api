from rest_framework.serializers import ModelSerializer

from files.models import UserFile


class UserFileSerializer(ModelSerializer[UserFile]):
    class Meta:
        model = UserFile
        fields = [
            "name",
            "extension",
            "mime_type",
            "size",
            "link",
            "user",
            "datetime_uploaded",
        ]
