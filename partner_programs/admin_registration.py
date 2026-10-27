"""Редактор анкеты в админке; схема и публикация общие с API организатора."""

from uuid import uuid4

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms import BaseFormSet, formset_factory
from django.http import Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from rest_framework.exceptions import APIException

from partner_programs.services import native_registration as registration
from partner_programs.services import program_launch


FIELD_TYPES = (
    ("text", "Короткий текст"),
    ("textarea", "Развернутый ответ"),
    ("number", "Число"),
    ("date", "Дата"),
    ("select", "Один вариант из списка"),
    ("multiselect", "Несколько вариантов"),
)
SOURCES = (
    ("own", "Свой список"),
    ("universities", "Справочник вузов"),
    ("regions", "Справочник регионов"),
)


def error_text(detail):
    if isinstance(detail, dict):
        # Служебные коды API не являются текстом интерфейса.
        return " ".join(
            error_text(v) for k, v in detail.items() if k not in ("code", "section")
        )
    if isinstance(detail, (list, tuple)):
        return " ".join(error_text(v) for v in detail)
    return str(detail)


class RegistrationForm(forms.Form):
    revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    mode = forms.ChoiceField(
        label="Способ регистрации",
        choices=(("native", "Через PROCOLLAB"), ("external", "Через внешний сайт")),
        widget=forms.RadioSelect,
    )
    confirm_archive = forms.BooleanField(
        label="Подтверждаю удаление полей из новой анкеты с сохранением прежних ответов",
        required=False,
    )


class RegistrationFieldForm(forms.Form):
    id = forms.RegexField(r"^f[a-f0-9]{32}$", required=False, widget=forms.HiddenInput)
    label = forms.CharField(label="Название поля", max_length=255)
    type = forms.ChoiceField(label="Тип ответа", choices=FIELD_TYPES)
    help_text = forms.CharField(
        label="Подсказка участнику", required=False, max_length=1000
    )
    required = forms.BooleanField(label="Обязательное поле", required=False)
    source = forms.ChoiceField(label="Источник вариантов", choices=SOURCES, initial="own")
    options = forms.CharField(
        label="Варианты ответа",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="По одному варианту на строке. Используется для своего списка.",
    )
    options_file = forms.FileField(
        label="Импортировать варианты из файла",
        required=False,
        help_text="XLSX или CSV в UTF-8: один столбец без заголовка, до 2 МБ.",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx,.csv"}),
    )
    allow_other = forms.BooleanField(label="Разрешить вариант «Другое»", required=False)

    def clean(self):
        data = super().clean()
        data["id"] = data.get("id") or "f" + uuid4().hex
        options = list(
            dict.fromkeys(
                v.strip() for v in data.get("options", "").splitlines() if v.strip()
            )
        )
        upload = data.get("options_file")
        if upload:
            if (
                data.get("type") not in ("select", "multiselect")
                or data.get("source") != "own"
            ):
                self.add_error(
                    "options_file", "Импорт доступен для поля со своим списком вариантов."
                )
            else:
                try:
                    result = registration.import_options(upload)
                    options = result["options"]
                    self.import_result = result
                except APIException as error:
                    self.add_error("options_file", error_text(error.detail))
        data["options"] = options
        return data


class RegistrationFieldFormSet(BaseFormSet):
    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["ORDER"].label = "Позиция в анкете"
        form.fields["ORDER"].widget.attrs["min"] = 1
        form.fields["DELETE"].label = "Убрать поле из новой анкеты"

    def schema(self, mode, *, publishing=False):
        fields = [
            {
                key: form.cleaned_data[key]
                for key in (
                    "id",
                    "label",
                    "type",
                    "help_text",
                    "required",
                    "source",
                    "options",
                    "allow_other",
                )
            }
            for form in self.ordered_forms
        ]
        return registration.clean_schema(
            {"mode": mode, "fields": fields}, publishing=publishing
        )


FieldFormSet = formset_factory(
    RegistrationFieldForm,
    formset=RegistrationFieldFormSet,
    extra=0,
    can_order=True,
    can_delete=True,
    max_num=100,
    validate_max=True,
    absolute_max=200,
)


class ConnectionForm(forms.Form):
    url = forms.URLField(label="Сайт мероприятия", max_length=200)
    comment = forms.CharField(
        label="Комментарий",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    contact = forms.CharField(label="Контакт для связи", required=False, max_length=500)

    def clean_url(self):
        value = self.cleaned_data["url"]
        if not value.startswith(("http://", "https://")):
            raise forms.ValidationError(
                "Укажите адрес сайта, начинающийся с http:// или https://."
            )
        return value


def field_initial(fields):
    return [{**field, "options": "\n".join(field["options"])} for field in fields]


def preview_form(schema):
    from partner_programs.registration_regions import REGIONS
    from users.models import University

    form = forms.Form()
    for field in schema["fields"]:
        common = dict(
            label=field["label"],
            help_text=field["help_text"],
            required=field["required"],
            disabled=True,
        )
        kind = field["type"]
        if kind in ("select", "multiselect"):
            options = field["options"]
            if field["source"] == "regions":
                options = REGIONS
            elif field["source"] == "universities":
                options = University.objects.filter(is_active=True).values_list(
                    "name", flat=True
                )
            choices = [(v, v) for v in options]
            if field["allow_other"]:
                choices.append(("__other__", "Другое"))
            cls = (
                forms.MultipleChoiceField if kind == "multiselect" else forms.ChoiceField
            )
            item = cls(choices=choices, **common)
        elif kind == "number":
            item = forms.FloatField(**common)
        elif kind == "date":
            item = forms.DateField(
                widget=forms.DateInput(attrs={"type": "date"}), **common
            )
        else:
            item = forms.CharField(
                widget=forms.Textarea if kind == "textarea" else forms.TextInput, **common
            )
        form.fields[field["id"]] = item
    return form


class ProgramRegistrationAdminMixin:
    def get_urls(self):
        return [
            path(
                "<int:object_id>/registration/",
                self.admin_site.admin_view(self.registration_view),
                name="partner_programs_partnerprogram_registration",
            )
        ] + super().get_urls()

    def registration_view(self, request, object_id):
        program = self.get_object(request, str(object_id))
        if program is None:
            raise Http404
        if not self.has_change_permission(request, program):
            raise PermissionDenied
        state = registration.settings_data(program)
        initial = {"revision": state["revision"], "mode": state["draft"]["mode"]}
        bound = (
            request.method == "POST"
            and request.POST.get("action") != "request_connection"
        )
        form = RegistrationForm(request.POST if bound else None, initial=initial)
        fields = FieldFormSet(
            request.POST if bound else None,
            request.FILES if bound else None,
            initial=field_initial(state["draft"]["fields"]),
            prefix="fields",
        )
        connection = ConnectionForm(
            initial={
                "url": state["connection_website_url"],
                "comment": state["connection_comment"],
                "contact": state["connection_contact"],
            }
        )
        preview = None
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "request_connection":
                connection = ConnectionForm(request.POST)
                if connection.is_valid():
                    try:
                        registration.request_connection(
                            program.pk, request.user, connection.cleaned_data
                        )
                    except APIException as error:
                        connection.add_error(None, error_text(error.detail))
                    else:
                        self.message_user(
                            request, "Запрос на подключение отправлен администратору."
                        )
                        return HttpResponseRedirect(request.path)
            elif form.is_valid() and fields.is_valid():
                try:
                    schema = fields.schema(
                        form.cleaned_data["mode"], publishing=action == "publish"
                    )
                    if action in ("save", "publish"):
                        removed = set(state["answered_field_ids"]) & (
                            {f["id"] for f in state["draft"]["fields"]}
                            - {f["id"] for f in schema["fields"]}
                        )
                        if removed and not form.cleaned_data["confirm_archive"]:
                            form.add_error(
                                "confirm_archive",
                                "На удаляемые поля уже есть ответы. Подтвердите их архивирование.",
                            )
                        else:
                            with transaction.atomic():
                                # Проверка версии и блокировка те же, что при сохранении с фронта.
                                registration.save_settings(
                                    program.pk,
                                    request.user,
                                    {
                                        "revision": form.cleaned_data["revision"],
                                        "draft": schema,
                                    },
                                    publish=action == "publish",
                                )
                                current = program_launch.readiness(
                                    program.pk, request.user
                                )
                                if action == "publish" and current["program"]["draft"]:
                                    program_launch.publish_program(
                                        program.pk, request.user, current["revision"]
                                    )
                                self.log_change(
                                    request,
                                    program,
                                    "Опубликована форма регистрации."
                                    if action == "publish"
                                    else "Сохранен черновик регистрации.",
                                )
                            self.message_user(
                                request,
                                "Форма регистрации опубликована."
                                if action == "publish"
                                else "Черновик регистрации сохранен.",
                            )
                            return HttpResponseRedirect(request.path)
                    elif action in ("preview", "add", "import"):
                        if action == "preview":
                            preview = preview_form(schema)
                        rows = field_initial(schema["fields"])
                        if action == "add":
                            if len(rows) >= 100:
                                form.add_error(
                                    None, "В анкете может быть не более 100 полей."
                                )
                            else:
                                rows.append(
                                    {
                                        "id": "f" + uuid4().hex,
                                        "type": "text",
                                        "source": "own",
                                    }
                                )
                        for item in fields:
                            if hasattr(item, "import_result"):
                                result = item.import_result
                                self.message_user(
                                    request,
                                    f"Импортировано вариантов: {len(result['options'])}. "
                                    f"Повторов: {result['duplicates']}. "
                                    f"Пустых строк: {result['blanks']}.",
                                    messages.INFO,
                                )
                        fields = FieldFormSet(initial=rows, prefix="fields")
                    else:
                        form.add_error(None, "Выберите действие с формой регистрации.")
                except APIException as error:
                    form.add_error(None, error_text(error.detail))
        config = registration.config_for(program)
        context = {
            **self.admin_site.each_context(request),
            "title": f"Регистрация: {program.name}",
            "opts": self.model._meta,
            "original": program,
            "program": program,
            "form": form,
            "fields": fields,
            "connection": connection,
            "preview": preview,
            "state": state,
            "change_url": reverse(
                "admin:partner_programs_partnerprogram_change", args=[program.pk]
            ),
            "connection_url": reverse(
                "admin:partner_programs_programregistration_change", args=[config.pk]
            )
            if config
            and request.user.has_perm("partner_programs.change_programregistration")
            else None,
        }
        return TemplateResponse(
            request, "partner_programs/admin/registration.html", context
        )
