import logging
import sys
import re
from loguru import logger


def redact_expert_invitation_token(message):
    return re.sub(
        r"(/evaluation/invitations/)[A-Za-z0-9_-]{20,100}", r"\1[redacted]", message
    )


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, redact_expert_invitation_token(record.getMessage())
        )
