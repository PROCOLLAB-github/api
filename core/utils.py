import os
import logging
import pandas as pd

from django.core.mail import EmailMultiAlternatives


logger = logging.getLogger()


class Email:
    """
    Send email messages
    """

    @staticmethod
    def send_email(data):
        email = EmailMultiAlternatives(
            subject=data["email_subject"],
            body=data["email_body"],
            to=[data["to_email"]],
        )
        if data.get("html_content"):
            email.attach_alternative(data["html_content"], "text/html")
        email.send()


def get_user_online_cache_key(user) -> str:
    return f"online_user_{user.pk}"


def get_users_online_cache_key() -> str:
    return "online_users"


class XlsxFileToExport:
    """
    Writing data to `xlsx` file.
    `filename` must contain `.xlsx` format prefix.
    All data on 1 page.
    """

    def __init__(self, filename="output.xlsx"):
        self.filename = filename

    def write_data_to_xlsx(self, data: list[dict], sheet_name: str = "scores") -> None:
        try:
            data_frames = pd.DataFrame(data)
            with pd.ExcelWriter(self.filename) as writer:
                data_frames.to_excel(writer, sheet_name=sheet_name, index=False)
        except Exception as e:
            logger.error(f"Write export rates data error: {str(e)}", exc_info=True)
            raise

    def get_binary_data_from_self_file(self) -> bytes:
        try:
            with open(self.filename, "rb") as f:
                binary_data = f.read()
            return binary_data
        except Exception as e:
            logger.error(f"Read export rates data error: {str(e)}", exc_info=True)
            raise

    def delete_self_xlsx_file_from_local_machine(self) -> None:
        if os.path.isfile(self.filename) and self.filename.endswith(".xlsx"):
            os.remove(self.filename)
