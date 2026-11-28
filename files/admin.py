import reprlib

from django.contrib import admin, messages
from django.contrib.admin.actions import delete_selected
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.forms import ModelForm, FileField
from django.db.models import QuerySet
from django.shortcuts import redirect

from chats.attachments import ATTACHMENT_IN_USE, used_by_visible_chat_message
from files.exceptions import SelectelDeleteError
from files.service import CDN, SelectelSwiftStorage
from files.models import UserFile
from partner_programs.solution_files import used_by_submitted_solution


def file_deletion_error(file):
    if used_by_submitted_solution(file.pk):
        return "Файл используется в сохраненном решении."
    if used_by_visible_chat_message(file.pk):
        return ATTACHMENT_IN_USE
    return None


class UserFileForm(ModelForm):
    file = FileField(required=True)

    class Meta:
        model = UserFile
        fields = "__all__"


@admin.register(UserFile)
class UserFileAdmin(admin.ModelAdmin):
    form = UserFileForm
    readonly_fields = ("detected_mime_type",)
    actions = ("delete_selected",)

    def get_deleted_objects(self, objs, request):
        deleted, counts, permissions_needed, protected = super().get_deleted_objects(
            objs, request
        )
        for obj in objs:
            if error := file_deletion_error(obj):
                protected.append(f"{obj} — {error}")
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

    def delete_view(self, request, object_id, extra_context=None):
        try:
            return super().delete_view(request, object_id, extra_context)
        except SelectelDeleteError as error:
            self.message_user(request, str(error), level=messages.ERROR)
            return redirect(request.get_full_path())

    @transaction.atomic
    def delete_model(self, request, obj):
        obj = UserFile.objects.select_for_update().get(pk=obj.pk)
        if error := file_deletion_error(obj):
            raise PermissionDenied(error)
        self.cdn.delete(obj.link)
        obj.delete()

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        rows = list(queryset.select_for_update().order_by("pk"))
        for obj in rows:
            if error := file_deletion_error(obj):
                raise PermissionDenied(error)
        deleted = []
        for obj in rows:
            try:
                self.cdn.delete(obj.link)
            except SelectelDeleteError:
                continue
            deleted.append(obj)
        if deleted:
            self.log_deletions(request, deleted)
            queryset.filter(pk__in=[obj.pk for obj in deleted]).delete()
        return len(deleted), len(rows) - len(deleted)

    @admin.action(permissions=["delete"], description="Удалить выбранные файлы")
    def delete_selected(self, request, queryset):
        if not request.POST.get("post"):
            return delete_selected(self, request, queryset)
        _, _, permissions_needed, protected = self.get_deleted_objects(queryset, request)
        if protected:
            return delete_selected(self, request, queryset)
        if permissions_needed:
            raise PermissionDenied
        deleted, failed = self.delete_queryset(request, queryset)
        if deleted:
            self.message_user(request, f"Удалено файлов: {deleted}.", messages.SUCCESS)
        if failed:
            self.message_user(
                request,
                f"Не удалось удалить файлов: {failed}. Повторите попытку.",
                messages.ERROR,
            )
        return None

    def get_queryset(self, request) -> QuerySet[UserFile]:
        qs = super().get_queryset(request)
        if request.user.groups.filter(name="Руководитель программы").exists():
            return qs.filter(user=request.user)
        return qs
