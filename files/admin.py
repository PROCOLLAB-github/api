import reprlib

from django.contrib import admin
from django.forms import ModelForm, FileField

from files.helpers import FileAPI
from files.models import UserFile


class UserFileForm(ModelForm):
    file = FileField(required=True)

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

    def save_model(self, request, obj, form, change):
        file_api = FileAPI(request.FILES["file"], request.user)
        info = file_api.upload()
        obj.link = info.url
        obj.user = request.user
        obj.name = info.name
        obj.size = info.size
        obj.extension = info.extension
        obj.mime_type = info.mime_type
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        FileAPI.delete(obj.link)
        obj.delete()

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            FileAPI.delete(obj.link)
            obj.delete()
