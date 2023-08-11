import mimetypes
import time

import magic
import requests
import webp
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from PIL import Image

from files.exceptions import SelectelUploadError
from files.typings import FileAPIUploadInfo
from procollab.settings import (
    DEBUG,
    SELECTEL_ACCOUNT_ID,
    SELECTEL_CONTAINER_NAME,
    SELECTEL_CONTAINER_PASSWORD,
    SELECTEL_CONTAINER_USERNAME,
)

User = get_user_model()

SUPPORTED_IMAGES_TYPES = (
    mimetypes.types_map[".jpg"],
    mimetypes.types_map[".png"],
)


class File:
    def __init__(self, file: TemporaryUploadedFile | InMemoryUploadedFile):
        self.size = file.size
        self.name = File._get_name(file)
        self.extension = File._get_extension(file)
        self.mime_type = File._get_mime_type(file)
        self.buffer = file.open(mode="rb")
        self.content_type = file.content_type

        if self.mime_type in SUPPORTED_IMAGES_TYPES:
            webp_image = convert_image_to_webp(file)
            self.buffer = webp_image.buffer()
            self.size = webp_image.size
            self.mime_type = "image/webp"
            self.extension = "webp"

    @staticmethod
    def _get_mime_type(file: TemporaryUploadedFile | InMemoryUploadedFile):
        if isinstance(file, InMemoryUploadedFile):
            buffer = file.open(mode="rb")
            return magic.from_buffer(buffer.read(), mime=True)
        return magic.from_file(file.temporary_file_path(), mime=True)

    @staticmethod
    def _get_extension(file) -> str:
        if len(file.name.split(".")) > 1:
            return file.name.split(".")[-1]
        return ""

    @staticmethod
    def _get_name(file) -> str:
        name_parts = file.name.split(".")
        if len(name_parts) == 1:
            return name_parts[0]
        return ".".join(name_parts[:-1])


class FileAPI:
    def __init__(
        self,
        file: TemporaryUploadedFile | InMemoryUploadedFile,
        user: User,
    ) -> None:
        self.file = File(file)
        self.user = user

    @staticmethod
    def delete(url: str) -> int:
        """Deletes file from selcdn"""
        token = FileAPI._get_selectel_swift_token()
        response = requests.delete(url, headers={"X-Auth-Token": token})
        return response.status_code

    def upload(self) -> FileAPIUploadInfo:
        url = self._upload_via_selectel_swift()
        return FileAPIUploadInfo(
            url=url,
            name=self.file.name,
            extension=self.file.extension,
            mime_type=self.file.mime_type,
            size=self.file.size,
        )

    def _upload_via_selectel_swift(self) -> str:
        token = self._get_selectel_swift_token()
        url = self._generate_selectel_swift_file_url()

        requests.put(
            url,
            headers={
                "X-Auth-Token": token,
                "Content-Type": self.file.content_type,
            },
            data=self.file.buffer,
        )

        return url

    def _generate_selectel_swift_file_url(self) -> str:
        """
        Generates url for selcdn
        Returns:
            url: str looks like /hashedEmail/hashedFilename_hashedTime.extension
        """
        link = self._generate_selectel_swift_link()
        return (
            f"{link}"
            f"{abs(hash(self.user.email))}"
            f"/{abs(hash(self.file.name))}"
            f"_{abs(hash(time.time()))}"
            f".{self.file.extension}"
        )

    @staticmethod
    def _generate_selectel_swift_link():
        link = f"https://api.selcdn.ru/v1/SEL_{SELECTEL_ACCOUNT_ID}/{SELECTEL_CONTAINER_NAME}/"
        if DEBUG:
            link += "debug/"
        return link

    @staticmethod
    def _get_selectel_swift_token():
        """Returns auth token for selcdn"""
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
        response = requests.post("https://api.selcdn.ru/v3/auth/tokens", json=data)
        if response.status_code not in [200, 201]:
            raise SelectelUploadError("Couldn't generate a token for selcdn")
        return response.headers["x-subject-token"]


def convert_image_to_webp(image, quality: int = 70):
    config = webp.WebPConfig.new(preset=webp.WebPPreset.PHOTO, quality=quality)
    pil_image = Image.open(image.file)
    webp_image = webp.WebPPicture.from_pil(pil_image)
    return webp_image.encode(config)
