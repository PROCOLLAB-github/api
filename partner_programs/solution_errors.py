"""Ошибки C00 для HTTP и транзакционных сервисов решений."""

from rest_framework.exceptions import APIException

MAX_ID = 2**53 - 1


class SolutionError(APIException):
    def __init__(self, code, detail, status=409, *, errors=None, meta=None):
        self.status_code = status
        self.payload = dict(
            code=code, detail=detail, errors=errors or [], meta=meta or {}
        )
        super().__init__(detail=detail, code=code)


def issue(path, code, detail, field_id=None):
    return dict(path=path, code=code, detail=detail, field_id=field_id)
