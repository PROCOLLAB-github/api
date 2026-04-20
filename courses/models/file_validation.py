ALLOWED_IMAGE_EXTENSIONS = {
    "bmp",
    "gif",
    "jpg",
    "jpeg",
    "png",
    "svg",
    "webp",
}


def looks_like_image_file(
    *,
    mime_type: str | None = None,
    extension: str | None = None,
) -> bool:
    normalized_mime_type = (mime_type or "").strip().lower()
    if normalized_mime_type.startswith("image/"):
        return True

    normalized_extension = (extension or "").strip().lower().lstrip(".")
    return normalized_extension in ALLOWED_IMAGE_EXTENSIONS
