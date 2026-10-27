"""Настройки доступа пользователя в стандартной карточке администратора."""

from django import forms
from django.contrib.auth.models import Permission

from partner_programs.permissions import PROGRAM_CREATION_PERMISSION
from users.models import CustomUser


class CustomUserAdminForm(forms.ModelForm):
    can_create_programs = forms.BooleanField(
        label="Может создавать программы",
        required=False,
        help_text="Разрешает создавать новые программы на платформе.",
    )

    class Meta:
        model = CustomUser
        fields = "__all__"
        labels = {
            "is_staff": "Доступ к админке",
            "is_superuser": "Все права (суперпользователь)",
            "groups": "Группы доступа",
            "user_permissions": "Другие разрешения",
        }
        help_texts = {
            "is_staff": "Разрешает вход в административную панель.",
            "is_superuser": "Предоставляет все разрешения, включая создание программ.",
            "groups": "Пользователь получает разрешения выбранных групп.",
            "user_permissions": "Дополнительные личные разрешения пользователя.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        app_label, codename = PROGRAM_CREATION_PERMISSION.split(".")
        self.creation_permission = Permission.objects.get(
            content_type__app_label=app_label, codename=codename
        )
        permission_id = self.creation_permission.pk
        direct = False
        inherited = False
        if self.instance.pk:
            direct = self.instance.user_permissions.filter(pk=permission_id).exists()
            inherited = self.instance.groups.filter(permissions=permission_id).exists()
        self.direct_creation_permission = direct
        self.inherited_creation_permission = self.instance.is_superuser or inherited
        checkbox = self.fields["can_create_programs"]
        self.initial["can_create_programs"] = direct or self.inherited_creation_permission
        if self.inherited_creation_permission:
            checkbox.disabled = True
            checkbox.help_text = (
                "Создание программ доступно благодаря статусу суперпользователя."
                if self.instance.is_superuser
                else "Право выдано через группу доступа. Чтобы его отозвать, измените группы пользователя."
            )
        if "user_permissions" in self.fields:
            # У одного разрешения один элемент управления; остальные права сохраняются штатно.
            self.fields["user_permissions"].queryset = self.fields[
                "user_permissions"
            ].queryset.exclude(pk=permission_id)
            self.initial["user_permissions"] = (
                list(
                    self.instance.user_permissions.exclude(pk=permission_id).values_list(
                        "pk", flat=True
                    )
                )
                if self.instance.pk
                else []
            )

    def clean(self):
        data = super().clean()
        if "user_permissions" in data:
            permissions = list(data["user_permissions"])
            # Группа или суперпользователь не должны превращаться в скрытую личную выдачу.
            grant = (
                self.direct_creation_permission
                if self.inherited_creation_permission
                else data.get("can_create_programs", False)
            )
            if grant:
                permissions.append(self.creation_permission)
            data["user_permissions"] = permissions
        return data

    def _save_m2m(self):
        super()._save_m2m()
        for cache in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            self.instance.__dict__.pop(cache, None)
