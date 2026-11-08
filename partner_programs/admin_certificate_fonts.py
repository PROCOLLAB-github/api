from copy import deepcopy

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from rest_framework.exceptions import ValidationError

from partner_programs.certificate_models import (
    ProgramCertificateAsset,
    ProgramCertificateConfig,
)
from partner_programs.services import certificates


class CertificateFontsForm(forms.Form):
    element = forms.ChoiceField(
        label="Текстовый элемент",
        choices=[
            ("name", "Имя участника"),
            ("title", "Заголовок"),
            ("subtitle", "Подзаголовок"),
            ("program", "Название программы"),
            ("date", "Дата выдачи"),
            ("number", "Номер сертификата"),
            ("director", "Имя директора"),
            ("position", "Должность"),
        ],
    )
    font = forms.ChoiceField(label="Шрифт")
    upload = forms.FileField(
        label="Загрузить шрифт для выбранного элемента",
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ".ttf,.otf"}),
        help_text="TTF или OTF до 2 МБ.",
    )
    revision = forms.IntegerField(widget=forms.HiddenInput())

    def __init__(self, *args, program, config, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["revision"].initial = config.revision
        self.fields["font"].choices = [
            ("mont", "Mont"),
            ("mont-regular", "Mont Regular"),
            ("mont-light", "Mont Light"),
            ("mont-bold", "Mont Bold"),
            ("pt-serif", "PT Serif"),
            ("lobster", "Lobster"),
            *[
                (f"custom-{pk}", name)
                for pk, name in ProgramCertificateAsset.objects.filter(
                    program=program, kind="font"
                ).values_list("pk", "name")
            ],
        ]
        self.fields["font"].initial = config.draft["layout"]["name"].get(
            "font_family", "mont"
        )


class ProgramCertificateFontsAdminMixin:
    def get_urls(self):
        return [
            path(
                "<int:object_id>/certificate-fonts/",
                self.admin_site.admin_view(self.certificate_fonts),
                name="partner_programs_partnerprogram_certificate_fonts",
            ),
            *super().get_urls(),
        ]

    def certificate_fonts(self, request, object_id):
        program = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.has_change_permission(request, program):
            raise PermissionDenied
        config = certificates.config_for(program)
        form = CertificateFontsForm(
            request.POST or None, request.FILES or None, program=program, config=config
        )
        if request.method == "POST" and form.is_valid():
            try:
                with transaction.atomic():
                    type(program).objects.select_for_update().get(pk=program.pk)
                    current = ProgramCertificateConfig.objects.select_for_update().get(
                        pk=config.pk
                    )
                    data = form.cleaned_data
                    if current.revision != data["revision"]:
                        raise ValidationError("Шаблон уже изменен. Обновите страницу.")
                    font = data["font"]
                    if data["upload"]:
                        font = f"custom-{certificates.upload_font(program, data['upload']).pk}"
                    draft = deepcopy(current.draft)
                    draft["layout"][data["element"]]["font_family"] = font
                    current.draft = certificates.validate_draft(
                        program, draft, current.draft
                    )
                    current.revision += 1
                    current.save(update_fields=["draft", "revision"])
            except ValidationError as error:
                form.add_error(None, " ".join(map(str, error.detail)))
            else:
                self.message_user(request, "Шрифт элемента сохранен.", messages.SUCCESS)
                return redirect(
                    "admin:partner_programs_partnerprogram_certificate_fonts", object_id
                )
        return TemplateResponse(
            request,
            "partner_programs/admin/certificate_fonts.html",
            {
                **self.admin_site.each_context(request),
                "title": "Шрифты сертификата",
                "program": program,
                "form": form,
                "change_url": reverse(
                    "admin:partner_programs_partnerprogram_change", args=[object_id]
                ),
            },
        )
