import asyncio
import json
from datetime import time
from asgiref.sync import sync_to_async
from aiohttp import ClientSession
from django.db import transaction
from django.utils.decorators import classonlymethod
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from files.models import UserFile
from procollab.settings import (
    DEBUG,
    SELECTEL_ACCOUNT_ID,
    SELECTEL_CONTAINER_NAME,
    SELECTEL_CONTAINER_PASSWORD,
    SELECTEL_CONTAINER_USERNAME,
)


class FileUploadView(APIView):
    permission_classes = [permissions.AllowAny]

    @classonlymethod
    def as_view(cls, **initkwargs):
        view = super().as_view(**initkwargs)
        view._is_coroutine = asyncio.coroutines._is_coroutine
        return view

    @transaction.atomic
    async def post(self, request):
        file = request.FILES["file"]
        if DEBUG is True:
            return Response(
                {"message": "Files doesn't save in development mode, sorry <3"},
                status=status.HTTP_406_NOT_ACCEPTABLE,
            )

        link = f"https://api.selcdn.ru/v1/SEL_{SELECTEL_ACCOUNT_ID}/{SELECTEL_CONTAINER_NAME}/"

        user = request.user

        # creates UserFile object in the database
        self._save_to_db(user, link)
        token = await self._get_token()
        async with ClientSession(headers={"X-Auth-Token": token}) as server:
            if len(file.split(".")) > 1:
                extension = file.filename.split(".")[1]
            else:
                extension = ""

            # looks like /hashed_email/hashed_filename_hashed_time.extension
            url = (
                link + f"/{SELECTEL_CONTAINER_NAME}/{abs(hash(user.email))}/"
                f"{abs(hash(file.filename))}_{abs(hash(time.time()))}.{extension}"
            )

            async with server.put(
                url,
                data=file.open(mode="rb").read(),
            ) as response:
                if response.status != 201:
                    return await Response(
                        "Failed to upload file", status_code=status.HTTP_409_CONFLICT
                    )
                return await Response({"url": url}, status=status.HTTP_201_CREATED)

    @sync_to_async
    def _save_to_db(self, user, link):
        """creates userfile object for file uploads"""
        return UserFile.objects.create(user=user, link=link)

    async def _get_token(self):
        """returns auth token for sentry"""
        async with ClientSession() as server:
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
            async with server.post(
                "https://api.selcdn.ru/v3/auth/tokens",
                data=json.dumps(data),
            ) as response:
                if response.status != 201:
                    return Response(
                        "Failed to get token", status_code=status.HTTP_409_CONFLICT
                    )
                return response.json()
