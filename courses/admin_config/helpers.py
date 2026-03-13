from django import forms

from files.models import UserFile
from files.service import CDN, SelectelSwiftStorage

from courses.models.file_validation import looks_like_image_file


def validate_image_upload(
    form: forms.ModelForm,
    field_name: str,
    error_message: str,
) -> None:
    uploaded_file = form.cleaned_data.get(field_name)
    if uploaded_file and not looks_like_image_file(
        mime_type=getattr(uploaded_file, "content_type", ""),
        extension=getattr(uploaded_file, "name", "").rsplit(".", 1)[-1],
    ):
        form.add_error(field_name, error_message)


class UserFileUploadAdminMixin:
    cdn = CDN(storage=SelectelSwiftStorage())

    def create_user_file(self, request, uploaded_file):
        info = self.cdn.upload(uploaded_file, request.user, quality=100)
        return UserFile.objects.create(
            link=info.url,
            user=request.user,
            name=info.name,
            size=info.size,
            extension=info.extension,
            mime_type=info.mime_type,
        )
