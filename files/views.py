import time

import requests
from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from files.exceptions import SelectelUploadError
from files.models import UserFile
from procollab.settings import (
    DEBUG,
    SELECTEL_ACCOUNT_ID,
    SELECTEL_CONTAINER_NAME,
    SELECTEL_CONTAINER_PASSWORD,
    SELECTEL_CONTAINER_USERNAME,
)


class FileView(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request):
        if DEBUG is True:
            return Response(
                {"message": "Files doesn't save in development mode, sorry <3"},
                status=status.HTTP_406_NOT_ACCEPTABLE,
            )

        file = request.FILES["file"]
        link = f"https://api.selcdn.ru/v1/SEL_{SELECTEL_ACCOUNT_ID}/{SELECTEL_CONTAINER_NAME}/"
        user = request.user
        token = self._get_token()

        if len(file.name.split(".")) > 1:
            extension = file.name.split(".")[1]
        else:
            extension = ""

        # looks like /hashedEmail/hashedFilename_hashedTime.extension
        url = (
            link + f"{SELECTEL_CONTAINER_NAME}/{abs(hash(user.email))}/"
            f"{abs(hash(file.name))}_{abs(hash(time.time()))}{'.' + extension if extension else ''}"
        )
        with file.open(mode="rb") as file_object:
            r = requests.put(
                url,
                headers={"X-Auth-Token": token, "Content-Type": file_object.content_type},
                data=file_object.read(),
            )
        if r.status_code != 201:
            return Response("Failed to upload file", status=status.HTTP_409_CONFLICT)
        self._save_to_db(user, url)
        return Response({"url": url}, status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        try:
            UserFile.objects.get(pk=pk).delete()
        except UserFile.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_200_OK)

    @classmethod
    def _save_to_db(cls, user, url):
        """creates userfile object for file uploads"""
        return UserFile.objects.create(user=user, link=url)

    @classmethod
    def _get_token(cls):
        """returns auth token for sentry"""
        data = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "id": SELECTEL_CONTAINER_USERNAME,
                            "password": SELECTEL_CONTAINER_PASSWORD,
                        }
                    },
                }
            }
        }
        r = requests.post("https://api.selcdn.ru/v3/auth/tokens", json=data)
        if r.status_code not in [200, 201]:
            raise SelectelUploadError("couldn't generate a token for selcdn")
        return r.headers["x-subject-token"]
        # async with server.post(
        #     "https://api.selcdn.ru/v3/auth/tokens",
        #     data=json.dumps(data),
        # ) as response:
        #     if response.status != 201:
        #         return Response(
        #             "Failed to get token", status_code=status.HTTP_409_CONFLICT
        #         )
        #     return response.json()
