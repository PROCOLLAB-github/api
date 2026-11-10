import time
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from uuid import uuid4
from abc import ABC, abstractmethod

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from requests import Response

from files.constants import SUPPORTED_IMAGES_TYPES
from files.content import detect_content_type
from files.exceptions import SelectelUploadError
from files.helpers import convert_image_to_webp
from files.typings import FileInfo
from procollab.settings import SELECTEL_SWIFT_URL

User = get_user_model()


class File:
    def __init__(
        self,
        file: TemporaryUploadedFile | InMemoryUploadedFile,
        quality: int = 70,
        *,
        preserve_original: bool = False,
    ):
        self.size = file.size
        self.name = File._get_name(file)
        self.extension = File._get_extension(file)
        self.buffer = file.open(mode="rb")
        self.content_type = file.content_type

        # we can compress given type of image
        if self.content_type in SUPPORTED_IMAGES_TYPES and not preserve_original:
            webp_image = convert_image_to_webp(file, quality)
            self.buffer = webp_image.buffer()
            self.size = webp_image.size
            self.content_type = "image/webp"
            self.extension = "webp"
        self.detected_mime_type = (
            detect_content_type(self.buffer) if self.size <= 104857600 else ""
        )

    @staticmethod
    def _get_name(file) -> str:
        name_parts = file.name.split(".")
        if len(name_parts) == 1:
            return name_parts[0]
        return ".".join(name_parts[:-1])

    @staticmethod
    def _get_extension(file) -> str:
        if len(file.name.split(".")) > 1:
            return file.name.split(".")[-1]
        return ""


class Storage(ABC):
    @abstractmethod
    def delete(self, url: str) -> Response:
        pass

    @abstractmethod
    def upload(self, file: File, user: User) -> FileInfo:
        pass


class SelectelSwiftStorage(Storage):
    def delete(self, url: str) -> Response:
        token = self._get_auth_token()
        return requests.delete(url, headers={"X-Auth-Token": token})

    def upload(self, file: File, user: User) -> FileInfo:
        url = self._upload(file, user)
        return FileInfo(
            url=url,
            name=file.name,
            extension=file.extension,
            mime_type=file.content_type,
            size=file.size,
            detected_mime_type=file.detected_mime_type,
        )

    def _upload(self, file: File, user: User) -> str:
        token = self._get_auth_token()
        url = self._generate_url(file, user)

        requests.put(
            url,
            headers={
                "X-Auth-Token": token,
                "Content-Type": file.content_type,
            },
            data=file.buffer,
        )

        return url

    def _generate_url(self, file: File, user: User) -> str:
        """
        Generates url for selcdn
        Returns:
            url: str looks like /hashedEmail/hashedFilename_hashedTime.extension
        """
        return (
            f"{SELECTEL_SWIFT_URL}"
            f"{abs(hash(user.email))}"
            f"/{abs(hash(file.name))}"
            f"_{abs(hash(time.time()))}"
            f".{file.extension}"
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


class PilotFileStorage(Storage):
    """Файлы изолированного пилота не используют общий контейнер Selectel."""

    def __init__(self):
        self.storage = FileSystemStorage()

    def upload(self, file: File, user: User) -> FileInfo:
        suffix = f".{file.extension}" if file.extension else ""
        name = self.storage.save(f"uploads/{user.pk}/{uuid4().hex}{suffix}", file.buffer)
        return FileInfo(
            url=settings.WHITE_LABEL_FRONTEND_URL.rstrip("/") + self.storage.url(name),
            name=file.name,
            extension=file.extension,
            mime_type=file.content_type,
            size=file.size,
            detected_mime_type=file.detected_mime_type,
        )

    def delete(self, url: str) -> Response:
        origin = settings.WHITE_LABEL_FRONTEND_URL.rstrip("/")
        prefix = origin + settings.MEDIA_URL
        if not url.startswith(prefix):
            raise ValueError("Файл не принадлежит хранилищу пилота.")
        offset = len(settings.MEDIA_URL)
        name = unquote(urlsplit(url).path[offset:])
        if (
            not name
            or PurePosixPath(name).is_absolute()
            or ".." in PurePosixPath(name).parts
            or "\\" in name
        ):
            raise ValueError("Некорректный путь файла.")
        self.storage.delete(name)
        response = Response()
        response.status_code = 204
        return response


def configured_storage() -> Storage:
    if getattr(settings, "PILOT_LOCAL_FILES", False):
        return PilotFileStorage()
    return SelectelSwiftStorage()


class CDN:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def delete(self, url: str) -> Response:
        return self.storage.delete(url)

    def upload(
        self,
        file: TemporaryUploadedFile | InMemoryUploadedFile,
        user: User,
        quality: int = 70,
        *,
        preserve_original: bool = False,
    ) -> FileInfo:
        return self.storage.upload(
            File(file, quality, preserve_original=preserve_original), user
        )
