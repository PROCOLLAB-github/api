"""Русский интерфейс админки независимо от языка публичного API."""

from django.urls import reverse
from django.utils import translation


class AdminRussianLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path_info.startswith(reverse("admin:index")):
            return self.get_response(request)
        with translation.override("ru"):
            request.LANGUAGE_CODE = "ru"
            response = self.get_response(request)
            response.setdefault("Content-Language", "ru")
            return response
