import time
from abc import ABC, abstractmethod

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from requests import Response

from files.constants import SUPPORTED_IMAGES_TYPES
from files.exceptions import SelectelUploadError
from files.helpers import convert_image_to_webp
from files.typings import FileInfo
from procollab.settings import SELECTEL_SWIFT_URL

User = get_user_model()


class File:
    def __init__(
        self,
        file_obj: TemporaryUploadedFile | InMemoryUploadedFile,
        quality: int = 70,
    ):
        self.size = file_obj.size
        self.name = File._get_name(file_obj)
        self.extension = File._get_extension(file_obj)
        self.buffer = file_obj.open(mode="rb")
        self.content_type = file_obj.content_type

        # we can compress given type of image
        if self.content_type in SUPPORTED_IMAGES_TYPES:
            webp_image = convert_image_to_webp(file_obj, quality)
            self.buffer = webp_image.buffer()
            self.size = webp_image.size
            self.content_type = "image/webp"
            self.extension = "webp"

    @staticmethod
    def _get_name(file_obj) -> str:
        file_name_parts = file_obj.name.split(".")
        if len(file_name_parts) == 1:
            return file_name_parts[0]
        return ".".join(file_name_parts[:-1])

    @staticmethod
    def _get_extension(file_obj) -> str:
        file_name_parts = file_obj.name.split(".")
        if len(file_name_parts) > 1:
            return file_name_parts[-1]
        return ""


class Storage(ABC):
    @abstractmethod
    def delete(self, url: str) -> Response:
        pass

    @abstractmethod
    def upload(self, file_obj: File, user: User) -> FileInfo:
        pass


class SelectelSwiftStorage(Storage):
    def delete(self, url: str) -> Response:
        token = self._get_auth_token()
        return requests.delete(url, headers={"X-Auth-Token": token})

    def upload(self, file_obj: File, user: User) -> FileInfo:
        url = self._upload(file_obj, user)
        return FileInfo(
            url=url,
            name=file_obj.name,
            extension=file_obj.extension,
            mime_type=file_obj.content_type,
            size=file_obj.size,
        )

    def _upload(self, file_obj: File, user: User) -> str:
        token = self._get_auth_token()
        url = self._generate_url(file_obj, user)

        requests.put(
            url,
            headers={
                "X-Auth-Token": token,
                "Content-Type": file_obj.content_type,
            },
            data=file_obj.buffer,
        )

        return url

    def _generate_url(self, file_obj: File, user: User) -> str:
        """
        Generates url for selcdn
        Returns:
            url: str looks like /hashedEmail/hashedFilename_hashedTime.extension
        """
        return (
            f"{SELECTEL_SWIFT_URL}"
            f"{abs(hash(user.email))}"
            f"/{abs(hash(file_obj.name))}"
            f"_{abs(hash(time.time()))}"
            f".{file_obj.extension}"
        )

    @staticmethod
    def _get_auth_token():
        """
        Returns auth token
        """

        data = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "id": settings.SELECTEL_CONTAINER_USERNAME,
                            "password": settings.SELECTEL_CONTAINER_PASSWORD,
                        }
                    },
                }
            }
        }
        response = requests.post(settings.SELECTEL_AUTH_TOKEN_URL, json=data)
        if response.status_code not in [200, 201]:
            raise SelectelUploadError(
                "Couldn't generate a token for Selectel Swift API (selcdn)"
            )
        return response.headers["x-subject-token"]


class CDN:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def delete(self, url: str) -> Response:
        return self.storage.delete(url)

    def upload(
        self,
        file_obj: TemporaryUploadedFile | InMemoryUploadedFile,
        user: User,
        quality: int = 70,
    ) -> FileInfo:
        return self.storage.upload(File(file_obj, quality), user)
