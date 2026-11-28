import requests
from django.db import transaction
from rest_framework import generics
from rest_framework import permissions, status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from chats.attachments import ATTACHMENT_IN_USE, used_by_visible_chat_message
from files.exceptions import SelectelDeleteError, SelectelUploadError
from files.service import CDN, SelectelSwiftStorage, create_user_upload
from files.models import UserFile
from files.serializers import UserFileSerializer


class FileView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = UserFileSerializer
    queryset = UserFile.objects.all()

    cdn = CDN(storage=SelectelSwiftStorage())

    @transaction.atomic
    def post(self, request):
        """
        Creates a UserFile object and uploads the file to Selectel
        """

        if "file" not in request.FILES:
            return Response(
                {
                    "code": "validation_error",
                    "detail": "Выберите файл.",
                    "errors": [],
                    "meta": {},
                },
                status=400,
            )
        original = request.query_params.get("preserve_original", "false")
        if original not in ("true", "false"):
            return Response(
                {
                    "code": "validation_error",
                    "detail": "preserve_original должен быть true или false.",
                    "errors": [],
                    "meta": {},
                },
                status=400,
            )
        try:
            upload = create_user_upload(
                self.cdn,
                request.FILES["file"],
                request.user,
                preserve_original=original == "true",
            )
        except (requests.RequestException, SelectelUploadError, KeyError):
            return Response(
                {"detail": "Не удалось загрузить файл. Повторите попытку."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"url": upload.pk}, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        """deletes the file (only if the request is sent by the user who owns it!)
        The link has to be specified in the JSON body, not in the URL arguments.
        """
        # get the link from the query
        if request.query_params and (request.query_params.get("link") is not None):
            link = request.query_params.get("link")
        else:
            return Response(
                {
                    "error": "you have to pass the link of the object you want to delete in query parameters"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        instance = get_object_or_404(self.get_queryset().select_for_update(), link=link)
        if instance.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        from partner_programs.solution_files import protect_solution_file
        from partner_programs.solution_errors import SolutionError

        try:
            protect_solution_file(instance)
        except SolutionError as error:
            return Response(error.payload, status=error.status_code)
        if used_by_visible_chat_message(instance.pk):
            return Response(
                {"code": "chat_attachment_in_use", "detail": ATTACHMENT_IN_USE},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            self.cdn.delete(instance.link)
        except SelectelDeleteError as error:
            return Response(
                {"code": "file_delete_failed", "detail": str(error)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
