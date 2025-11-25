import copy
import logging

from django.conf import settings
from loguru import logger

from core.log.utils import InterceptHandler


def _add_logger_handler(path: str, level: str) -> None:
    """
    Attach loguru handler, falling back to synchronous mode if multiprocessing
    queues are not permitted (e.g. limited dev envs).
    """
    kwargs = copy.deepcopy(settings.LOGURU_LOGGING)
    try:
        logger.add(path, level=level, **kwargs)
    except PermissionError:
        kwargs.pop("enqueue", None)
        logger.add(path, level=level, **kwargs)


class CustomLoguruMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

        if settings.DEBUG:
            _add_logger_handler(f"{settings.BASE_DIR}/log/debug.log", "DEBUG")
        _add_logger_handler(f"{settings.BASE_DIR}/log/info.log", "INFO")
        _add_logger_handler(f"{settings.BASE_DIR}/log/warning.log", "WARNING")

    def __call__(self, request):
        response = self.get_response(request)
        logger.info(f"{request.method} {request.get_full_path()}")
        return response

    def process_exception(self, request, exception):
        logger.warning(f"{exception} http_path={request.get_full_path()}")
