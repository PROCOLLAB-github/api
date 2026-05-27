import time
from io import BytesIO
from pathlib import Path
from abc import ABC, abstractmethod
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from django.utils.text import get_valid_filename
from requests import Response

from files.constants import SUPPORTED_IMAGES_TYPES
from files.exceptions import SelectelUploadError
from files.helpers import convert_image_to_webp
from files.typings import FileInfo

User = get_user_model()


def iter_file_chunks(buffer, chunk_size: int = 1024 * 1024):
    if hasattr(buffer, "read"):
        for chunk in iter(lambda: buffer.read(chunk_size), b""):
            yield chunk
        return

    yield bytes(buffer)


class File:
    def __init__(
        self,
        file: TemporaryUploadedFile | InMemoryUploadedFile,
        quality: int = 70,
        convert_images: bool = True,
    ):
        self.size = file.size
        self.name = File._get_name(file)
        self.extension = File._get_extension(file)
        self.buffer = file.open(mode="rb")
        self.content_type = file.content_type

        # we can compress given type of image
        if convert_images and self.content_type in SUPPORTED_IMAGES_TYPES:
            webp_image = convert_image_to_webp(file, quality)
            self.buffer = BytesIO(bytes(webp_image.buffer()))
            self.size = webp_image.size
            self.content_type = "image/webp"
            self.extension = "webp"

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
    def __init__(self) -> None:
        required_settings = (
            "SELECTEL_SWIFT_URL",
            "SELECTEL_CONTAINER_USERNAME",
            "SELECTEL_CONTAINER_PASSWORD",
        )
        missing = [name for name in required_settings if not getattr(settings, name, "")]
        if missing:
            raise ImproperlyConfigured(
                "Selectel storage is not configured: " + ", ".join(missing)
            )

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
            f"{settings.SELECTEL_SWIFT_URL}"
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


class LocalFileSystemStorage(Storage):
    def delete(self, url: str) -> Response | None:
        parsed_url = urlparse(url)
        media_url = settings.MEDIA_URL.rstrip("/") + "/"
        if not parsed_url.path.startswith(media_url):
            return None

        relative_path = parsed_url.path.removeprefix(media_url)
        file_path = (Path(settings.MEDIA_ROOT) / relative_path).resolve()
        media_root = Path(settings.MEDIA_ROOT).resolve()

        if media_root not in file_path.parents and file_path != media_root:
            return None

        file_path.unlink(missing_ok=True)
        return None

    def upload(self, file: File, user: User) -> FileInfo:
        relative_path = self._generate_relative_path(file, user)
        file_path = Path(settings.MEDIA_ROOT) / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with file_path.open("wb") as destination:
            for chunk in iter_file_chunks(file.buffer):
                destination.write(chunk)

        return FileInfo(
            url=self._build_public_url(relative_path),
            name=file.name,
            extension=file.extension,
            mime_type=file.content_type,
            size=file.size,
        )

    def _generate_relative_path(self, file: File, user: User) -> Path:
        filename = get_valid_filename(file.name) or "file"
        extension = get_valid_filename(file.extension)
        stored_filename = (
            f"{abs(hash(filename))}_{abs(hash(time.time()))}"
            f"{f'.{extension}' if extension else ''}"
        )
        return Path("uploads") / str(abs(hash(user.email))) / stored_filename

    def _build_public_url(self, relative_path: Path) -> str:
        media_url = settings.MEDIA_URL.rstrip("/") + "/"
        base_url = settings.LOCAL_MEDIA_BASE_URL.rstrip("/")
        parsed_base = urlparse(base_url)

        if parsed_base.path.rstrip("/") == media_url.rstrip("/"):
            return urljoin(base_url + "/", relative_path.as_posix())

        return urljoin(
            base_url + "/",
            f"{media_url.lstrip('/')}{relative_path.as_posix()}",
        )


def get_default_storage() -> Storage:
    if getattr(settings, "FILE_STORAGE", "local") == "local":
        return LocalFileSystemStorage()
    if settings.FILE_STORAGE == "selectel":
        return SelectelSwiftStorage()
    raise ImproperlyConfigured("FILE_STORAGE must be either 'local' or 'selectel'.")


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
        preserve_original: bool = False,
    ) -> FileInfo:
        return self.storage.upload(
            File(file, quality, convert_images=not preserve_original),
            user,
        )
