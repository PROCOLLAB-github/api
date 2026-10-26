"""Определение типа по содержимому; не меняет допустимые типы общего upload."""

import codecs
import zipfile
from io import BytesIO

from PIL import Image, UnidentifiedImageError


def detect_content_type(stream):
    # The existing WebP encoder returns a cffi buffer rather than a seekable file.
    if not hasattr(stream, "seek"):
        stream = BytesIO(bytes(stream))
    position = stream.tell()
    try:
        stream.seek(0)
        header = stream.read(65536)
        if header.startswith(b"%PDF-"):
            return "application/pdf"
        stream.seek(0)
        if header.startswith((b"PK\x03\x04", b"PK\x05\x06")) and zipfile.is_zipfile(
            stream
        ):
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                names = set(archive.namelist())
            if "[Content_Types].xml" in names:
                for name, mime in (
                    (
                        "word/document.xml",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                    (
                        "ppt/presentation.xml",
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    ),
                    (
                        "xl/workbook.xml",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                ):
                    if name in names:
                        return mime
            return "application/zip"
        stream.seek(0)
        try:
            with Image.open(stream) as image:
                kind = image.format
                image.verify()
            return Image.MIME.get(kind, "application/octet-stream")
        except (UnidentifiedImageError, OSError, ValueError):
            pass
        if header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            return "application/x-ole-storage"
        if len(header) > 12 and header[4:8] == b"ftyp":
            return "video/mp4"
        if header.startswith(b"ID3") or header[:2] in (
            b"\xff\xfb",
            b"\xff\xf3",
            b"\xff\xf2",
        ):
            return "audio/mpeg"
        if header.startswith(b"OggS"):
            return "application/ogg"
        if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
            return "audio/wav"
        if b"\x00" not in header:
            try:
                codecs.getincrementaldecoder("utf-8")().decode(header, final=False)
                return "text/plain"
            except UnicodeDecodeError:
                pass
        return "application/octet-stream"
    except (zipfile.BadZipFile, Image.DecompressionBombError, OSError):
        return "application/octet-stream"
    finally:
        stream.seek(position)
