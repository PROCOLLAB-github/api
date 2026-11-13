from urllib.parse import unquote, urlsplit

import requests
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.handlers.asgi import ASGIRequest
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.utils.http import content_disposition_header

from files.exceptions import SelectelUploadError
from files.service import SelectelSwiftStorage


def is_storage_url(link):
    try:
        base = urlsplit(settings.SELECTEL_SWIFT_URL)
        target = urlsplit(link)
        path = unquote(target.path)
        prefix = unquote(base.path).rstrip("/") + "/"
        return (
            target.scheme == base.scheme == "https"
            and target.netloc.lower() == base.netloc.lower()
            and not target.username
            and not target.password
            and not target.query
            and not target.fragment
            and path.startswith(prefix)
            and len(path) > len(prefix)
            and "\\" not in path
            and "%" not in path
            and not any(ord(char) < 32 or ord(char) == 127 for char in path)
            and all(segment not in ("", ".", "..") for segment in path[1:].split("/"))
        )
    except ValueError:
        return False


def download_filename(file):
    name = file.name + (f".{file.extension}" if file.extension else "")
    name = "".join(
        char if char not in "/\\" and ord(char) >= 32 and ord(char) != 127 else "_"
        for char in name
    ).strip(" .")
    return name or "Вложение"


class DownloadBody:
    def __init__(self, upstream):
        self.upstream = upstream
        self.chunks = upstream.iter_content(chunk_size=64 * 1024)

    def __iter__(self):
        return iter(self.chunks)

    async def iter_async(self):
        # Django buffers synchronous iterators under ASGI. Pull one chunk at a time.
        next_chunk = sync_to_async(next, thread_sensitive=False)
        while (chunk := await next_chunk(self.chunks, None)) is not None:
            yield chunk

    def close(self):
        self.upstream.close()


def download_stored_file(request, file):
    if not is_storage_url(file.link):
        raise Http404("Вложение недоступно.")
    try:
        upstream = requests.get(
            file.link,
            headers={
                "X-Auth-Token": SelectelSwiftStorage._get_auth_token(),
                "Accept-Encoding": "identity",
            },
            stream=True,
            timeout=(5, 15),
            allow_redirects=False,
        )
    except (requests.RequestException, SelectelUploadError, KeyError):
        return storage_unavailable()

    if upstream.status_code != 200:
        upstream.close()
        if upstream.status_code == 404:
            raise Http404("Файл не найден в хранилище.")
        return storage_unavailable()

    raw_request = getattr(request, "_request", request)
    content_type = "application/octet-stream"
    if raw_request.method == "HEAD":
        upstream.close()
        response = HttpResponse(content_type=content_type)
    else:
        body = DownloadBody(upstream)
        if isinstance(raw_request, ASGIRequest):
            body = AsyncDownloadBody(body)
        response = StreamingHttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(
        as_attachment=True, filename=download_filename(file)
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    length = upstream.headers.get("Content-Length", "")
    if (
        length.isascii()
        and length.isdecimal()
        and not upstream.headers.get("Content-Encoding")
    ):
        response["Content-Length"] = length
    return response


class AsyncDownloadBody:
    def __init__(self, body):
        self.body = body

    def __aiter__(self):
        return self.body.iter_async()

    def close(self):
        self.body.close()


def storage_unavailable():
    response = HttpResponse(
        "Не удалось скачать файл. Повторите попытку.",
        status=502,
        content_type="text/plain; charset=utf-8",
    )
    response["Cache-Control"] = "private, no-store"
    return response
