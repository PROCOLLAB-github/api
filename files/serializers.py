from rest_framework.serializers import ModelSerializer

from files.models import UserFile


class UserFileSerializer(ModelSerializer):
    class Meta:
        model = UserFile
        fields = ["user", "link", "datetime_uploaded"]
