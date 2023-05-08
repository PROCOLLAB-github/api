from loguru import logger
from django.conf import settings
import logging
from logs.utils import InterceptHandler


class CustomLoguruMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
        if settings.DEBUG:
            logger.add(
                f"{settings.BASE_DIR}/logs/debug.log",
                level="DEBUG",
                rotation=settings.LOGURU_LOGGING["ROTATION"],
                compression=settings.LOGURU_LOGGING["COMPRESSION"],
            )
        logger.add(
            f"{settings.BASE_DIR}/logs/info.log",
            level="INFO",
            rotation=settings.LOGURU_LOGGING["ROTATION"],
            compression=settings.LOGURU_LOGGING["COMPRESSION"],
        )
        logger.add(
            f"{settings.BASE_DIR}/logs/warning.log",
            level="WARNING",
            rotation=settings.LOGURU_LOGGING["ROTATION"],
            compression=settings.LOGURU_LOGGING["COMPRESSION"],
        )

    def __call__(self, request):
        responce = self.get_response(request)
        logger.info(f"URL: {request.get_full_path()}")
        logger.info(f"Method: {request.method}")
        return responce

    def process_exception(self, request, exception):
        logger.warning(f"{exception} http_path={request.get_full_path()}")
