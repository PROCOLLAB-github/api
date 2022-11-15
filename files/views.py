from django.db import transaction
from rest_framework import generics
from rest_framework import permissions, status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from files.helpers import FileAPI
from files.models import UserFile
from files.serializers import UserFileSerializer


class FileView(generics.RetrieveDestroyAPIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = UserFileSerializer
    queryset = UserFile.objects.all()

    @transaction.atomic
    def post(self, request):
        """creates a UserFile object and uploads the file to selectel"""
        file_api = FileAPI(request.FILES["file"], request.user)
        status_code, url = file_api.upload()

        if status_code == 201:
            UserFile.objects.create(user=request.user, link=url)
            return Response({"url": url}, status=status.HTTP_201_CREATED)

        return Response("Failed to upload file", status=status.HTTP_409_CONFLICT)

    def delete(self, request, *args, **kwargs):
        """deletes the file (only if the request is sent by the user who owns it!)
        The link has to be specified in the JSON body, not in the URL arguments.
        """
        if request.data and (request.data.get("link") is not None):
            link = request.data.get("link")
        else:
            return Response(
                {
                    "error": "you have to pass the link of the object you want to delete as JSON"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        instance = get_object_or_404(self.get_queryset(), link=link)
        if instance.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        FileAPI.delete(instance.link)  # delete the file via api
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)
