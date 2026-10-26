from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Q

from partner_programs.models import PartnerProgram
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionMember,
    ProgramSolutionAnswer,
    SolutionInvitation,
    SolutionAdministrativeChange,
    SolutionRegistrationRemoval,
)


class ReadonlySolutionInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SolutionAdministrativeChange)
class SolutionAdministrativeChangeAdmin(admin.ModelAdmin):
    list_display = ("id", "solution", "action", "actor_name", "created_at")
    list_filter = ("action", "was_submitted", "solution__program")
    search_fields = ("solution__name", "actor_name")
    readonly_fields = tuple(
        field.name for field in SolutionAdministrativeChange._meta.fields
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SolutionRegistrationRemoval)
class SolutionRegistrationRemovalAdmin(SolutionAdministrativeChangeAdmin):
    list_display = ("id", "program", "actor_name", "deleted_count", "created_at")
    list_filter = ("program",)
    search_fields = ("actor_name",)
    readonly_fields = tuple(
        field.name for field in SolutionRegistrationRemoval._meta.fields
    )


class SolutionMemberInline(ReadonlySolutionInline):
    model = ProgramSolutionMember
    verbose_name = "Участник команды"
    verbose_name_plural = "Принятый состав"
    fields = ("user", "role", "specialization", "joined_at")
    readonly_fields = fields


class SolutionAnswerInline(ReadonlySolutionInline):
    model = ProgramSolutionAnswer
    verbose_name = "Ответ"
    verbose_name_plural = "Ответы решения"
    fields = ("field", "value")
    readonly_fields = fields


class SolutionInvitationInline(ReadonlySolutionInline):
    model = SolutionInvitation
    verbose_name = "Приглашение"
    verbose_name_plural = "Приглашения команды"
    fields = ("recipient", "role", "status", "created_at")
    readonly_fields = fields


@admin.register(ProgramSolution)
class ProgramSolutionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "program",
        "captain",
        "status",
        "submitted_at",
        "archived_at",
    )
    list_filter = ("program", "status")
    search_fields = ("name", "program__name", "captain__email")
    inlines = (SolutionMemberInline, SolutionAnswerInline, SolutionInvitationInline)

    def get_queryset(self, request):
        return ProgramSolution.all_objects.all()

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or obj.archived_at is None
        )

    def has_add_permission(self, request):
        return False

    @transaction.atomic
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST" and object_id:
            obj = self.get_object(request, object_id)
            if obj:
                PartnerProgram.objects.select_for_update().get(pk=obj.program_id)
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        if change and obj.status == "draft" and "name" in form.changed_data:
            obj.version += 1
        return super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        return tuple(
            field.name
            for field in self.model._meta.fields
            if not obj
            or obj.status == "submitted"
            or obj.archived_at
            or field.name != "name"
        )

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (
            obj is None or (obj.status != "submitted" and obj.archived_at is None)
        )

    def get_deleted_objects(self, objs, request):
        deleted, counts, needed, protected = super().get_deleted_objects(objs, request)
        protected.extend(
            f"Сохраненное решение #{obj.pk}"
            for obj in objs
            if obj.status == "submitted" or obj.archived_at
        )
        return deleted, counts, needed, protected

    @transaction.atomic
    def delete_view(self, request, object_id, extra_context=None):
        obj = self.get_object(request, object_id)
        if obj:
            PartnerProgram.objects.select_for_update().get(pk=obj.program_id)
        return super().delete_view(request, object_id, extra_context)

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        list(
            PartnerProgram.objects.select_for_update()
            .filter(pk__in=queryset.values("program_id"))
            .order_by("pk")
        )
        submitted = queryset.filter(
            Q(status="submitted") | Q(archived_at__isnull=False)
        ).count()
        queryset.filter(status="draft", archived_at__isnull=True).delete()
        if submitted:
            self.message_user(
                request,
                f"Защищенные решения сохранены: {submitted}.",
                level=messages.WARNING,
            )
