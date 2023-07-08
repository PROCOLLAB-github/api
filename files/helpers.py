import requests
import time
import magic
from django.core.files.uploadedfile import TemporaryUploadedFile

from files.exceptions import SelectelUploadError
from files.models import UserFile

from procollab.settings import (
    DEBUG,
    SELECTEL_ACCOUNT_ID,
    SELECTEL_CONTAINER_NAME,
    SELECTEL_CONTAINER_PASSWORD,
    SELECTEL_CONTAINER_USERNAME,
)


class FileAPI:
    def __init__(self, file: TemporaryUploadedFile, user) -> None:
        self.file = file  # it's TemporaryUploadedFile, and it will be
        # removed after first .close() call, so we must read this file only once
        self.user = user
        self.file_object = self.file.open(mode="rb")

    @staticmethod
    def delete(url: str) -> int:
        """Deletes file from selcdn"""
        token = FileAPI._get_selectel_swift_token()
        response = requests.delete(url, headers={"X-Auth-Token": token})
        return response.status_code

    def upload(self) -> str:
        url = self._upload_via_selectel_swift()
        info = get_file_info(self.file)
        UserFile.objects.create(
            user=self.user,
            link=url,
            name=info["name"],
            size=info["size"],
            extension=info["extension"],
            mime_type=info["mime_type"],
        )
        self.file_object.close()
        return url

    def _upload_via_selectel_swift(self) -> str:
        token = self._get_selectel_swift_token()
        url = self._generate_selectel_swift_file_url()

        requests.put(
            url,
            headers={
                "X-Auth-Token": token,
                "Content-Type": self.file_object.content_type,
            },
            data=self.file_object.read(),
        )

        return url

    def _generate_selectel_swift_link(sefl):
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

    def _get_file_extension(self) -> str:
        if len(self.file.name.split(".")) > 1:
            return "." + self.file.name.split(".")[1]
        return ""

    def _generate_selectel_swift_file_url(self) -> str:
        """
        Generates url for selcdn
        Returns:
            url: str looks like /hashedEmail/hashedFilename_hashedTime.extension
        """
        link = self._generate_selectel_swift_link()
        extension = self._get_file_extension()
        return (
            link
            + f"{abs(hash(self.user.email))}/{abs(hash(self.file.name))}_{abs(hash(time.time()))}{extension}"
        )


def get_file_info(file: TemporaryUploadedFile) -> dict:
    name, ext = file.name.split(".")

    return {
        "size": file.size,
        "name": name,
        "extension": ext,
        "mime_type": get_file_mime_type(file),
    }


def get_file_mime_type(file: TemporaryUploadedFile):
    return magic.from_file(file.temporary_file_path(), mime=True)
