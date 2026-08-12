from collections.abc import Mapping

from django.db import transaction
from rest_framework import serializers

from users.models import CustomUser, UserLink


class SocialLinksField(serializers.Field):
    """Проверяет частичное обновление типизированных социальных ссылок."""

    default_error_messages = {
        "not_object": "Ожидается объект социальных ссылок.",
        "unknown_kind": "Неизвестный тип социальной ссылки.",
        "invalid_url": "Укажите корректный URL.",
    }

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            self.fail("not_object")

        allowed_kinds = set(UserLink.Kind.values)
        unknown_kinds = set(data) - allowed_kinds
        if unknown_kinds:
            raise serializers.ValidationError(
                {
                    kind: self.error_messages["unknown_kind"]
                    for kind in sorted(unknown_kinds)
                }
            )

        url_field = serializers.URLField(allow_null=True)
        result: dict[str, str | None] = {}
        errors: dict[str, str] = {}
        for kind, value in data.items():
            try:
                result[kind] = url_field.run_validation(value)
            except serializers.ValidationError:
                errors[kind] = self.error_messages["invalid_url"]

        if errors:
            raise serializers.ValidationError(errors)
        return result

    def to_representation(self, value):
        return value


def get_social_links(user: CustomUser) -> dict[str, str]:
    """Возвращает словарь типизированных ссылок текущего пользователя."""

    return {link.kind: link.link for link in user.links.all() if link.kind is not None}


@transaction.atomic
def update_social_links(
    user: CustomUser,
    social_links: dict[str, str | None],
) -> None:
    """Обновляет только переданные типы, сохраняя legacy-ссылки и остальные ключи."""

    for kind, link in social_links.items():
        if link is None:
            UserLink.objects.filter(user=user, kind=kind).delete()
            continue
        UserLink.objects.update_or_create(
            user=user,
            kind=kind,
            defaults={"link": link},
        )
