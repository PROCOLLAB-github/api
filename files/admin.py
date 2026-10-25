import reprlib

from django.contrib import admin
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.forms import ModelForm, FileField
from django.db.models import QuerySet

from files.service import CDN, SelectelSwiftStorage
from files.models import UserFile


class UserFileForm(ModelForm):
    file = FileField(required=True)

    class Meta:
        model = UserFile
        fields = "__all__"


@admin.register(UserFile)
class UserFileAdmin(admin.ModelAdmin):
    form = UserFileForm
    readonly_fields = ("detected_mime_type",)

    def get_deleted_objects(self, objs, request):
        from partner_programs.solution_files import used_by_submitted_solution

        deleted, counts, permissions_needed, protected = super().get_deleted_objects(
            objs, request
        )
        for obj in objs:
            if used_by_submitted_solution(obj.pk):
                protected.append(f"Файл сохраненного решения: {obj}")
        return deleted, counts, permissions_needed, protected

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
    ordering = ("-datetime_uploaded",)

    cdn = CDN(storage=SelectelSwiftStorage())

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
        info = self.cdn.upload(request.FILES["file"], request.user, quality=100)
        obj.link = info.url
        obj.user = request.user
        obj.name = info.name
        obj.size = info.size
        obj.extension = info.extension
        obj.mime_type = info.mime_type
        obj.detected_mime_type = info.detected_mime_type
        super().save_model(request, obj, form, change)

    @transaction.atomic
    def delete_model(self, request, obj):
        from partner_programs.solution_files import used_by_submitted_solution

        obj = UserFile.objects.select_for_update().get(pk=obj.pk)
        if used_by_submitted_solution(obj.pk):
            raise PermissionDenied("Файл используется в сохраненном решении.")
        self.cdn.delete(obj.link)
        obj.delete()

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        from partner_programs.solution_files import used_by_submitted_solution

        rows = list(queryset.select_for_update().order_by("pk"))
        if any(used_by_submitted_solution(obj.pk) for obj in rows):
            raise PermissionDenied("Файл используется в сохраненном решении.")
        for obj in rows:
            self.cdn.delete(obj.link)
        queryset.delete()

    def get_queryset(self, request) -> QuerySet[UserFile]:
        qs = super().get_queryset(request)
        if request.user.groups.filter(name="Руководитель программы").exists():
            return qs.filter(user=request.user)
        return qs
