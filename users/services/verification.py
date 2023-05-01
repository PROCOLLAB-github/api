"""
A verification service that uses ClickUp API for creating tasks

When the user confirms his email, the service creates a task in the ClickUp Space with information
about the user so that the moderator can manually check the information about him
"""

import requests
from decouple import config
from django.contrib.auth import get_user_model

User = get_user_model()


class VerificationTasks:
    instance = None
    __TOKEN = config("CLICKUP_API_TOKEN", default="default-api-key", cast=str)
    __CLICKUP_SPACE_ID = config("CLICKUP_SPACE_ID", cast=int)

    @classmethod
    def create(cls, user: User):
        data = cls._collect_data(user)
        cls._send_request(data)

    @classmethod
    def _collect_data(cls, user: User):
        # todo DEBUG mode
        link_to_platform = f"https://app.procollab.ru/office/profile/{user.pk}/"
        link_to_admin_panel = (
            f"https://api.procollab.ru/admin/users/customuser/{user.pk}/change/"
        )

        priority = 3  # normal
        if user.user_type != User.MEMBER:
            priority = 1  # urgent

        description = f"Профиль в админке: {link_to_admin_panel}\nПрофиль на платформе: {link_to_platform}"
        name = f"{user.pk}: {user.first_name} {user.last_name}"

        return {
            "name": name,
            "priority": priority,
            "description": description,
        }

    @classmethod
    def _send_request(cls, data):
        try:
            url = f"https://api.clickup.com/api/v2/list/{cls.__CLICKUP_SPACE_ID}/task/"
            requests.post(
                url,
                data=data,
                headers={
                    "Authorization": cls.__TOKEN,
                },
            ).json()
        except Exception:
            # fixme
            pass


def __new__(cls, *args, **kwargs):
    if not hasattr(cls, "instance"):
        cls.instance = super().__new__(cls)
    return cls.instance
