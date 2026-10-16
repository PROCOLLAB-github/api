from rest_framework.exceptions import APIException


class TeamError(APIException):
    status_code = 409

    def __init__(self, code, detail, *, status_code=409):
        self.status_code = status_code
        super().__init__({"code": code, "detail": detail}, code=code)
