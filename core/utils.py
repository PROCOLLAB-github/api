import logging
import io
import unicodedata
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
    Формирует XLSX в памяти.
    `filename` сохранён для совместимости, но не используется для записи на диск.
    Все данные пишутся на один лист.
    """

    def __init__(self, filename="output.xlsx"):
        self.filename = filename
        self._buffer = None

    def write_data_to_xlsx(self, data: list[dict], sheet_name: str = "scores") -> None:
        try:
            data_frames = pd.DataFrame(data)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                data_frames.to_excel(writer, sheet_name=sheet_name, index=False)
            buffer.seek(0)
            self._buffer = buffer
        except Exception as e:
            logger.error(f"Write export rates data error: {str(e)}", exc_info=True)
            raise

    def get_binary_data_from_self_file(self) -> bytes:
        try:
            if not self._buffer:
                raise ValueError("XLSX buffer is empty")
            return self._buffer.getvalue()
        except Exception as e:
            logger.error(f"Read export rates data error: {str(e)}", exc_info=True)
            raise

    def clear_buffer(self) -> None:
        if self._buffer:
            self._buffer.close()
            self._buffer = None


def sanitize_filename(filename: str) -> str:
    normalized_name = unicodedata.normalize("NFKD", filename)
    safe_chars = [
        char
        for char in normalized_name
        if char.isalnum() or char in ("-", "_", " ", ".")
    ]
    cleaned_name = "".join(safe_chars)
    return " ".join(cleaned_name.split())


def ascii_filename(filename: str) -> str:
    safe_name = sanitize_filename(filename)
    ascii_name = "".join(char if char.isascii() else "_" for char in safe_name)
    ascii_name = " ".join(ascii_name.split())
    return ascii_name or "export"
