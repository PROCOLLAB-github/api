"""Возврат программы в черновик через общую с кабинетом бизнес-логику."""

from django import forms
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseNotAllowed, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from rest_framework.exceptions import APIException

from partner_programs.admin_registration import error_text
from partner_programs.services.program_launch import return_to_draft


class ReturnToDraftForm(forms.Form):
    expected_updated_at = forms.DateTimeField(widget=forms.HiddenInput)


class ProgramPublicationAdminMixin:
    def get_urls(self):
        return [
            path(
                "<int:object_id>/unpublish/",
                self.admin_site.admin_view(self.return_to_draft_view),
                name="partner_programs_partnerprogram_unpublish",
            )
        ] + super().get_urls()

    def return_to_draft_view(self, request, object_id):
        if request.method not in ("GET", "POST"):
            return HttpResponseNotAllowed(["GET", "POST"])
        program = self.get_object(request, str(object_id))
        if program is None:
            raise Http404
        if not self.has_change_permission(request, program):
            raise PermissionDenied
        change_url = reverse(
            "admin:partner_programs_partnerprogram_change", args=[program.pk]
        )
        form = ReturnToDraftForm(
            request.POST if request.method == "POST" else None,
            initial={"expected_updated_at": program.datetime_updated.isoformat()},
        )
        status = 200
        if request.method == "POST" and form.is_valid():
            try:
                program = return_to_draft(
                    program.pk, request.user, form.cleaned_data["expected_updated_at"]
                )
            except APIException as error:
                form.add_error(None, error_text(error.detail))
                status = error.status_code
            else:
                self.log_change(request, program, "Программа возвращена в черновик.")
                self.message_user(request, "Программа возвращена в черновик.")
                return HttpResponseRedirect(change_url)
        context = {
            **self.admin_site.each_context(request),
            "title": "Вернуть программу в черновик?",
            "opts": self.model._meta,
            "original": program,
            "form": form,
            "change_url": change_url,
        }
        return TemplateResponse(
            request, "partner_programs/admin/unpublish.html", context, status=status
        )
