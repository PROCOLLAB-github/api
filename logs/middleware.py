from loguru import logger
from django.conf import settings
import logging
from logs.utils import InterceptHandler
from procollab.settings import LOGURU_LOGGING


class CustomLoguruMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

        if settings.DEBUG:
            logger.add(
                f"{settings.BASE_DIR}/logs/debug.log",
                level="DEBUG",
                **LOGURU_LOGGING,
            )
        logger.add(
            f"{settings.BASE_DIR}/logs/info.log",
            level="INFO",
            **LOGURU_LOGGING,
        )
        logger.add(
            f"{settings.BASE_DIR}/logs/warning.log",
            level="WARNING",
            **LOGURU_LOGGING,
        )

    def __call__(self, request):
        response = self.get_response(request)
        logger.info(f"{request.method} {request.get_full_path()}")
        return response

    def process_exception(self, request, exception):
        logger.warning(f"{exception} http_path={request.get_full_path()}")
