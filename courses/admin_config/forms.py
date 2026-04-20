from django import forms
from django.forms.models import BaseInlineFormSet

from courses.models import Course, CourseModule, CourseTask

from .helpers import validate_image_upload


class OrderUniqueInlineFormSet(BaseInlineFormSet):
    duplicate_field_error = "Такой порядковый номер уже используется в этом разделе."
    duplicate_form_error = "Найдены дублирующиеся значения. Исправьте строки ниже."

    def get_unique_error_message(self, unique_check):
        if "order" in unique_check:
            return self.duplicate_field_error
        return super().get_unique_error_message(unique_check)

    def get_form_error(self):
        return self.duplicate_form_error

    def clean(self):
        super().clean()
        order_to_form = {}
        has_duplicates = False

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue

            order_value = form.cleaned_data.get("order")
            if order_value in (None, ""):
                continue

            previous_form = order_to_form.get(order_value)
            if previous_form is not None:
                previous_form.add_error("order", self.duplicate_field_error)
                form.add_error("order", self.duplicate_field_error)
                has_duplicates = True
            else:
                order_to_form[order_value] = form

        if has_duplicates:
            raise forms.ValidationError(self.duplicate_form_error)


class CourseAdminForm(forms.ModelForm):
    avatar_upload = forms.FileField(required=False, label="Аватар (загрузить файл)")
    card_cover_upload = forms.FileField(
        required=False,
        label="Обложка карточки (загрузить файл)",
    )
    header_cover_upload = forms.FileField(
        required=False,
        label="Обложка шапки (загрузить файл)",
    )

    class Meta:
        model = Course
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        validate_image_upload(
            self,
            "avatar_upload",
            "В поле аватара можно загрузить только файл изображения.",
        )
        validate_image_upload(
            self,
            "card_cover_upload",
            "В поле обложки карточки можно загрузить только файл изображения.",
        )
        validate_image_upload(
            self,
            "header_cover_upload",
            "В поле обложки шапки можно загрузить только файл изображения.",
        )
        return cleaned_data


class CourseModuleAdminForm(forms.ModelForm):
    avatar_upload = forms.FileField(required=False, label="Аватар (загрузить файл)")

    class Meta:
        model = CourseModule
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        validate_image_upload(
            self,
            "avatar_upload",
            "В поле аватара можно загрузить только файл изображения.",
        )
        return cleaned_data


class CourseTaskAdminForm(forms.ModelForm):
    image_upload = forms.FileField(
        required=False,
        label="Изображение (загрузить файл)",
    )
    attachment_upload = forms.FileField(required=False, label="Файл (загрузить)")

    class Meta:
        model = CourseTask
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        image_upload = cleaned_data.get("image_upload")
        attachment_upload = cleaned_data.get("attachment_upload")
        validate_image_upload(
            self,
            "image_upload",
            "В поле изображения можно загрузить только файл изображения.",
        )
        self.instance._has_pending_image_upload = bool(image_upload)
        self.instance._has_pending_attachment_upload = bool(attachment_upload)
        return cleaned_data
