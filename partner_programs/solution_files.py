"""Привязка зарегистрированных файлов и защита снимков сданных решений."""

import posixpath
import tempfile
from urllib.parse import unquote, urlsplit

import requests
from django.conf import settings

from files.content import detect_content_type
from files.models import UserFile
from partner_programs.solution_errors import SolutionError, issue
from partner_programs.solution_models import ProgramSolution, ProgramSolutionAnswer
from partner_programs.solution_schema import MAX_FILE_SIZE

MIME_BY_EXTENSION = {
    "pdf": {"application/pdf"},
    "zip": {
        "application/zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "doc": {"application/x-ole-storage"},
    "xls": {"application/x-ole-storage"},
    "ppt": {"application/x-ole-storage"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "webp": {"image/webp"},
    "gif": {"image/gif"},
    "tif": {"image/tiff"},
    "tiff": {"image/tiff"},
    "txt": {"text/plain"},
    "csv": {"text/plain"},
    "md": {"text/plain"},
    "json": {"text/plain"},
    "svg": {"text/plain"},
    "html": {"text/plain"},
    "css": {"text/plain"},
    "mp4": {"video/mp4"},
    "mp3": {"audio/mpeg"},
    "ogg": {"application/ogg"},
    "wav": {"audio/wav"},
}


def file_error(field, code, detail):
    raise SolutionError(
        "invalid_answers",
        "Проверьте загруженный файл.",
        status=400,
        errors=[issue(f"answers.{field['id']}", code, detail, field["id"])],
    )


def owned_file_urls(solution):
    values = solution.answers.filter(field__field_type="file").values_list(
        "value", flat=True
    )
    return {
        value["url"]
        for value in values
        if isinstance(value, dict) and isinstance(value.get("url"), str)
    }


def trusted_cdn_url(link):
    try:
        base, target = urlsplit(settings.SELECTEL_SWIFT_URL), urlsplit(link)
        prefix = posixpath.normpath(unquote(base.path)).rstrip("/") + "/"
        path = posixpath.normpath(unquote(target.path))
        return (
            target.scheme in ("http", "https")
            and target.scheme == base.scheme
            and target.netloc.lower() == base.netloc.lower()
            and not target.username
            and not target.password
            and path.startswith(prefix)
        )
    except ValueError:
        return False


def verify_legacy_upload(upload, maximum, field):
    """Проверяет прежнюю загрузку только в своем CDN, никогда по произвольному URL."""
    if upload.detected_mime_type:
        return
    if not trusted_cdn_url(upload.link):
        file_error(field, "file_unverified", "Загрузите файл через платформу повторно.")
    response = None
    try:
        response = requests.get(
            upload.link, stream=True, timeout=(5, 10), allow_redirects=False
        )
        if response.status_code != 200:
            file_error(
                field, "file_unavailable", "Файл недоступен. Загрузите его повторно."
            )
        with tempfile.SpooledTemporaryFile(max_size=1048576) as stream:
            size = 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > maximum:
                    file_error(
                        field, "file_too_large", "Размер файла превышает допустимый."
                    )
                stream.write(chunk)
            stream.seek(0)
            upload.detected_mime_type = detect_content_type(stream)
            upload.size = size
            upload.save(update_fields=["detected_mime_type", "size"])
    except requests.RequestException as error:
        try:
            file_error(
                field, "file_unavailable", "Не удалось проверить файл. Повторите попытку."
            )
        except SolutionError as controlled:
            raise controlled from error
    finally:
        if response is not None:
            response.close()


def validate_file(solution, field, value, *, owned_urls=None):
    try:
        upload = UserFile.objects.select_for_update().get(pk=value["url"])
    except UserFile.DoesNotExist:
        file_error(field, "file_not_found", "Файл не найден. Загрузите его повторно.")
    if upload.user_id != solution.captain_id and upload.link not in (
        owned_urls if owned_urls is not None else owned_file_urls(solution)
    ):
        file_error(field, "file_forbidden", "Этот файл недоступен для заявки.")
    rules = field["validation"]
    maximum = min(MAX_FILE_SIZE, rules["max_file_size_bytes"] or MAX_FILE_SIZE)
    if upload.size > maximum:
        file_error(field, "file_too_large", "Размер файла превышает допустимый.")
    extension = upload.extension.lower()
    if rules["allowed_extensions"] and extension not in rules["allowed_extensions"]:
        file_error(field, "file_type_not_allowed", "Выберите разрешенный тип файла.")
    verify_legacy_upload(upload, maximum, field)
    expected = MIME_BY_EXTENSION.get(extension)
    if expected and upload.detected_mime_type not in expected:
        file_error(
            field, "file_type_mismatch", "Содержимое файла не соответствует его типу."
        )
    return upload


def used_by_submitted_solution(link):
    if ProgramSolutionAnswer.objects.filter(
        solution__status="submitted", value__url=link
    ).exists():
        return True
    # Снимок остается источником истины и после переноса исторических записей.
    for snapshot in ProgramSolution.objects.filter(status="submitted").values_list(
        "submission_snapshot", flat=True
    ):
        if not isinstance(snapshot, dict):
            continue
        for answer in snapshot.get("answers", []):
            value = answer.get("value") if isinstance(answer, dict) else None
            if isinstance(value, dict) and value.get("url") == link:
                return True
    return False


def protect_solution_file(upload):
    if used_by_submitted_solution(upload.link):
        raise SolutionError("file_in_use", "Файл используется в сданном решении.")
