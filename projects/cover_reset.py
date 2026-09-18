"""Сброс обложки legacy-проекта без изменения глобальных прав на файлы."""

import logging
from functools import partial

from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import APIException

from files.models import UserFile
from files.service import CDN, SelectelSwiftStorage
from projects.models import DefaultProjectAvatar, DefaultProjectCover, Project

logger = logging.getLogger(__name__)
cdn = CDN(storage=SelectelSwiftStorage())


class DefaultCoverUnavailable(APIException):
    status_code = 409
    default_detail = {
        "code": "default_cover_unavailable",
        "detail": "Стандартная обложка временно недоступна.",
    }


def reset_project_cover(project: Project, user_id: int) -> dict:
    """Назначает обложку уже заблокированному и проверенному на запись проекту.

    Вызывается внутри atomic после проверки обычных прав ProjectDetail.
    Очистка запускается только после коммита: сбой CDN не должен вернуть
    проекту старый URL или представить успешный сброс как ошибку.
    """
    old_url = project.cover_image_address
    defaults = DefaultProjectCover.objects.filter(image__isnull=False).exclude(
        image_id=""
    )
    if defaults.filter(image_id=old_url).exists():
        return {"cover_image_address": old_url, "is_default_cover": True}

    default_url = defaults.order_by("?").values_list("image_id", flat=True).first()
    if not default_url:
        raise DefaultCoverUnavailable()

    project.cover_image_address = default_url
    project.save(update_fields=["cover_image_address", "datetime_updated"])
    transaction.on_commit(partial(cleanup_previous_cover, old_url, user_id))
    return {"cover_image_address": default_url, "is_default_cover": True}


def cleanup_previous_cover(old_url: str | None, user_id: int) -> None:
    """Удаляет только собственный неиспользуемый файл после фиксации сброса.

    Владение проектом не даёт владения UserFile. Системные обложки/аватары
    и файлы других проектов сохраняются даже при совпадении владельца.
    Исключения и HTTP-ошибки CDN не откатывают смену обложки; URL и текст
    исключений не попадают в лог, поскольку могут содержать закрытые данные.
    """
    if not old_url:
        return
    try:
        with transaction.atomic():
            old_file = (
                UserFile.objects.select_for_update()
                .filter(link=old_url, user_id=user_id)
                .first()
            )
            if old_file is None:
                return
            if (
                DefaultProjectCover.objects.filter(image_id=old_url).exists()
                or DefaultProjectAvatar.objects.filter(image_id=old_url).exists()
                or Project.objects.filter(
                    Q(cover_image_address=old_url)
                    | Q(image_address=old_url)
                    | Q(presentation_address=old_url)
                    | Q(cover_id=old_url)
                ).exists()
            ):
                return
            response = cdn.delete(old_url)
            if response.status_code != 404:
                response.raise_for_status()
            old_file.delete()
    except Exception:
        logger.warning("Не удалось очистить прежний файл после сброса обложки проекта.")
