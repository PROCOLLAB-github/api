from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from files.helpers import FileAPI
from files.models import UserFile


class FileView(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request):
        file_api = FileAPI(request.FILES["file"], request.user)
        status_code, url = file_api.upload()

        if status_code == 201:
            UserFile.objects.create(user=request.user, link=url)
            return Response({"url": url}, status=status.HTTP_201_CREATED)

        return Response("Failed to upload file", status=status.HTTP_409_CONFLICT)
