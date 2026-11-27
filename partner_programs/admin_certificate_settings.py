from copy import deepcopy
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST, require_safe
from rest_framework.exceptions import APIException, ValidationError

from partner_programs.admin_registration import error_text
from partner_programs.permissions import can_manage_program
from partner_programs.services import certificates
from partner_programs.services.certificate_journal import (
    ATTENTION_FILTERS,
    JOURNAL_FILTERS,
    CertificateJournal,
    published_archive,
    queue_selection,
)
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

PDF_JOURNAL_LABELS = {
    "pending": "Готовится",
    "ready": "Готов",
    "failed": "Ошибка PDF",
}
EMAIL_JOURNAL_LABELS = {
    "not_planned": "Не запланировано",
    "pending": "Ожидает отправки",
    "sending": "Отправляется",
    "sent": "Отправлено",
    "failed": "Ошибка отправки",
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
            path(
                "<int:object_id>/certificate-journal/",
                self.admin_site.admin_view(self.certificate_journal),
                name="partner_programs_partnerprogram_certificate_journal",
            ),
            path(
                "<int:object_id>/certificate-journal/zip/",
                self.admin_site.admin_view(self.certificate_journal_zip),
                name="partner_programs_partnerprogram_certificate_journal_zip",
            ),
            path(
                "<int:object_id>/certificate-journal/retry/",
                self.admin_site.admin_view(self.certificate_journal_retry),
                name="partner_programs_partnerprogram_certificate_journal_retry",
            ),
            *super().get_urls(),
        ]

    def _managed_certificate_program(self, request, object_id):
        program = get_object_or_404(self.get_queryset(request), pk=object_id)
        if not self.has_change_permission(request, program) or not can_manage_program(
            request.user, program
        ):
            raise PermissionDenied("У вас нет доступа к управлению этой программой.")
        return program

    @method_decorator(require_safe)
    def certificate_journal(self, request, object_id):
        program = self._managed_certificate_program(request, object_id)
        context = {
            **self.admin_site.each_context(request),
            "title": "Журнал сертификатов",
            "program": program,
            "change_url": reverse(
                "admin:partner_programs_partnerprogram_change", args=[object_id]
            ),
            "status_filters": JOURNAL_FILTERS.items(),
        }
        try:
            journal = CertificateJournal(program, request.GET)
        except ValidationError:
            context["error"] = "Проверьте фильтр, строку поиска и номер страницы."
            return TemplateResponse(
                request,
                "partner_programs/admin/certificate_journal.html",
                context,
                status=400,
            )

        page = journal.data()
        for row in page["results"]:
            row["pdf_label"] = PDF_JOURNAL_LABELS[row["pdf_status"]]
            row["email_label"] = EMAIL_JOURNAL_LABELS[row["email_status"]]
        query = journal.query
        offset, limit = query["offset"], query["limit"]
        if offset:
            context["previous_query"] = urlencode(
                {**query, "offset": max(0, offset - limit)}
            )
        if offset + limit < page["count"]:
            context["next_query"] = urlencode({**query, "offset": offset + limit})
        context.update(
            page=page,
            query=query,
            archive_query=urlencode(
                {"status": query["status"], "search": query["search"]}
            ),
            allow_retry=page["count"] and query["status"] in ATTENTION_FILTERS,
            revision=journal.config.revision if journal.config else 1,
        )
        return TemplateResponse(
            request, "partner_programs/admin/certificate_journal.html", context
        )

    @method_decorator(require_safe)
    def certificate_journal_zip(self, request, object_id):
        program = self._managed_certificate_program(request, object_id)
        try:
            journal = CertificateJournal(program, request.GET)
        except ValidationError:
            return HttpResponseBadRequest("Проверьте фильтр и строку поиска.")
        return published_archive(journal.rows)

    @method_decorator(require_POST)
    def certificate_journal_retry(self, request, object_id):
        self._managed_certificate_program(request, object_id)
        journal_url = reverse(
            "admin:partner_programs_partnerprogram_certificate_journal", args=[object_id]
        )
        try:
            with transaction.atomic():
                program = managed_program(object_id, request.user, lock=True)
                query = CertificateJournal(program, request.POST).query
                journal_url += "?" + urlencode(query)
                if query["status"] not in ATTENTION_FILTERS:
                    raise ValidationError("Выберите фильтр ошибок.")
                if request.POST.get("confirm") != "yes":
                    raise ValidationError("Подтвердите повтор обработки.")
                result = queue_selection(
                    program,
                    {
                        **query,
                        "revision": request.POST.get("revision"),
                        "action": "retry",
                        "all_matching": True,
                    },
                    request.build_absolute_uri("/").rstrip("/"),
                )
        except APIException as error:
            if error.status_code == 403:
                raise PermissionDenied(error_text(error.detail)) from error
            self.message_user(request, error_text(error.detail), messages.ERROR)
        else:
            if result["count"]:
                self.message_user(
                    request,
                    f"Поставлено в очередь на повтор: {result['count']}.",
                    messages.SUCCESS,
                )
            else:
                self.message_user(
                    request, "Ошибки по фильтру не найдены.", messages.INFO
                )
        return redirect(journal_url)

    def certificate_settings(self, request, object_id):
        program = self._managed_certificate_program(request, object_id)
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
