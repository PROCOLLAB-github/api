import requests
import time
from files.exceptions import SelectelUploadError

from procollab.settings import (
    DEBUG,
    SELECTEL_ACCOUNT_ID,
    SELECTEL_CONTAINER_NAME,
    SELECTEL_CONTAINER_PASSWORD,
    SELECTEL_CONTAINER_USERNAME,
)


class FileAPI:
    def __init__(self, file, user) -> None:
        self.file = file
        self.user = user

    @staticmethod
    def delete(url: str) -> int:
        """Deletes file from selcdn"""
        token = FileAPI._get_selectel_swift_token()
        response = requests.delete(url, headers={"X-Auth-Token": token})
        return response.status_code

    def upload(self):
        return self._upload_via_selectel_swift()

    def _upload_via_selectel_swift(self) -> tuple[int, str]:
        token = self._get_selectel_swift_token()
        url = self._generate_selectel_swift_file_url()

        with self.file.open(mode="rb") as file_object:
            response = requests.put(
                url,
                headers={"X-Auth-Token": token, "Content-Type": file_object.content_type},
                data=file_object.read(),
            )

        return response.status_code, url

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
        r = requests.post("https://api.selcdn.ru/v3/auth/tokens", json=data)
        if r.status_code not in [200, 201]:
            raise SelectelUploadError("Couldn't generate a token for selcdn")
        return r.headers["x-subject-token"]

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


def fetcher_info(request):
    info = {
        "size": request.size,
        "name": request.name,
        "extension": request.name.split(".")[-1],
    }
    return info
