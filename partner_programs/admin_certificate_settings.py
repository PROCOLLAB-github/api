from copy import deepcopy

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from rest_framework.exceptions import APIException

from partner_programs.admin_registration import error_text
from partner_programs.permissions import can_manage_program
from partner_programs.services import certificates
from partner_programs.services.management import managed_program


ELEMENT_LABELS = {
    "title": "Заголовок",
    "subtitle": "Подзаголовок",
    "name": "Имя участника",
    "program": "Название программы",
    "date": "Дата выдачи",
    "number": "Номер сертификата",
    "director": "Имя директора",
    "position": "Должность",
    "signature": "Подпись",
}


class CertificateSettingsForm(forms.Form):
    revision = forms.IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
        error_messages={
            code: "Обновите страницу и повторите сохранение."
            for code in ("invalid", "required", "min_value")
        },
    )
    title = forms.CharField(
        label="Текст заголовка",
        required=False,
        max_length=certificates.TITLE_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 2}),
        error_messages={
            "max_length": "Заголовок должен содержать не более %(limit_value)s символов.",
        },
    )

    def __init__(self, *args, config, **kwargs):
        super().__init__(*args, **kwargs)
        draft = certificates.normalized_draft(config.draft)
        self.initial.update(revision=config.revision, title=draft["title"])
        for key in certificates.ELEMENTS:
            self.fields[f"rotation_{key}"] = forms.IntegerField(
                label=ELEMENT_LABELS[key],
                min_value=certificates.MIN_ROTATION,
                max_value=certificates.MAX_ROTATION,
                initial=draft["layout"][key]["rotation"],
                error_messages={
                    "invalid": "Укажите угол поворота целым числом.",
                    "required": "Укажите угол поворота целым числом.",
                    "min_value": "Угол поворота должен быть от −180 до 180 градусов.",
                    "max_value": "Угол поворота должен быть от −180 до 180 градусов.",
                },
            )


class ProgramCertificateSettingsAdminMixin:
    def get_urls(self):
        return [
            path(
                "<int:object_id>/certificate-settings/",
                self.admin_site.admin_view(self.certificate_settings),
                name="partner_programs_partnerprogram_certificate_settings",
            ),
            *super().get_urls(),
        ]

    def certificate_settings(self, request, object_id):
        program = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.has_change_permission(request, program) or not can_manage_program(
            request.user, program
        ):
            raise PermissionDenied("У вас нет доступа к управлению этой программой.")

        config = certificates.config_for(program)
        form = CertificateSettingsForm(
            request.POST if request.method == "POST" else None,
            config=config,
        )
        if request.method == "POST" and form.is_valid():
            try:
                with transaction.atomic():
                    program = managed_program(object_id, request.user, lock=True)
                    current = certificates.draft_for_update(program, form.cleaned_data)
                    draft = deepcopy(current.draft)
                    draft["title"] = form.cleaned_data["title"]
                    for key, box in draft["layout"].items():
                        box["rotation"] = form.cleaned_data[f"rotation_{key}"]
                    certificates.save_draft(program, current, draft)
            except APIException as error:
                if error.status_code == 403:
                    raise PermissionDenied(error_text(error.detail)) from error
                form.add_error(None, error_text(error.detail))
            else:
                self.message_user(
                    request, "Настройки сертификата сохранены.", messages.SUCCESS
                )
                return redirect(
                    "admin:partner_programs_partnerprogram_certificate_settings",
                    object_id,
                )
        return TemplateResponse(
            request,
            "partner_programs/admin/certificate_settings.html",
            {
                **self.admin_site.each_context(request),
                "title": "Заголовок и поворот элементов сертификата",
                "program": program,
                "form": form,
                "change_url": reverse(
                    "admin:partner_programs_partnerprogram_change", args=[object_id]
                ),
            },
        )
