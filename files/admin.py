import reprlib

from django.contrib import admin
from django.forms import ModelForm, FileField
from django.shortcuts import redirect

from files.helpers import FileAPI
from files.models import UserFile


class UserFileForm(ModelForm):
    file = FileField(required=True)

    def save(self, commit=True):
        if self.cleaned_data.get("file"):
            print(self.cleaned_data.get("file"))
        return super().save(commit)

    class Meta:
        model = UserFile
        fields = "__all__"


@admin.register(UserFile)
class UserFileAdmin(admin.ModelAdmin):
    form = UserFileForm
    list_display = (
        "short_link",
        "filename",
        "user",
        "datetime_uploaded",
    )
    list_display_links = (
        "short_link",
        "filename",
        "user",
    )
    search_fields = (
        "link",
        "user__first_name",
        "user__last_name",
    )
    list_filter = (
        "user",
        "datetime_uploaded",
    )

    date_hierarchy = "datetime_uploaded"

    @admin.display(empty_value="Empty filename")
    def filename(self, obj):
        return obj.name

    @admin.display(empty_value="Empty link")
    def short_link(self, obj):
        return reprlib.repr(obj.link.lstrip("https://")).strip("'")

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        file_field_index = fieldsets[0][1]["fields"].index("file")
        if obj:
            # remove file field if file is already uploaded
            del fieldsets[0][1]["fields"][file_field_index]
        else:
            # remove other field
            fieldsets[0][1]["fields"] = ["file"]
        return fieldsets

    def response_add(self, request, obj, post_url_continue=None):
        if obj is None:
            file_api = FileAPI(request.FILES["file"], request.user)
            url = file_api.upload()
            return redirect(f"/admin/files/userfile/{url}")
        return super().response_add(request, obj, post_url_continue)

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            return
            # file_api = FileAPI(request.FILES["file"], request.user)
            # url = file_api.upload()
            # obj = UserFile.objects.get(pk=url)
        super().save_model(request, obj, form, change)
