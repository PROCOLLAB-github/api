from django.contrib import admin

from projects.models import (
    Achievement,
    Collaborator,
    Company,
    DefaultProjectAvatar,
    DefaultProjectCover,
    Project,
    ProjectCompany,
    ProjectGoal,
    ProjectLink,
    ProjectNews,
    Resource,
)


class ProjectGoalInline(admin.TabularInline):
    model = ProjectGoal
    extra = 0
    fields = ("title", "completion_date", "responsible", "is_done")
    show_change_link = True
    autocomplete_fields = ("responsible",)


class ProjectCompanyInline(admin.TabularInline):
    model = ProjectCompany
    extra = 1
    autocomplete_fields = ("company", "decision_maker")
    fields = ("company", "contribution", "decision_maker")
    verbose_name = "Партнёр проекта"
    verbose_name_plural = "Партнёры проекта"


class ResourceInline(admin.StackedInline):
    model = Resource
    extra = 0
    fields = ("type", "description", "partner_company")
    show_change_link = True
    verbose_name = "Ресурс"
    verbose_name_plural = "Ресурсы"

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        if obj is not None:
            qs = obj.companies.all()
            formset.form.base_fields["partner_company"].queryset = qs
        return formset


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "draft",
        "is_public",
        "is_company",
        "trl",
        "target_audience",
        "implementation_deadline",
    )
    list_display_links = ("id", "name")
    search_fields = ("name",)
    list_filter = ("draft", "is_public", "is_company", "trl")

    fieldsets = (
        (
            "Основная информация",
            {
                "fields": (
                    "name",
                    "description",
                    "leader",
                    "industry",
                    "region",
                    "draft",
                    "is_public",
                    "is_company",
                )
            },
        ),
        (
            "Характеристики проекта",
            {
                "fields": (
                    "actuality",
                    "problem",
                    "target_audience",
                    "trl",
                    "implementation_deadline",
                )
            },
        ),
        (
            "Медиа и обложка",
            {
                "fields": (
                    "presentation_address",
                    "image_address",
                    "cover",
                    "cover_image_address",
                )
            },
        ),
        (
            "Служебные поля",
            {
                "fields": (
                    "hidden_score",
                    "datetime_created",
                    "datetime_updated",
                )
            },
        ),
    )
    readonly_fields = ("datetime_created", "datetime_updated")
    inlines = [ProjectGoalInline, ProjectCompanyInline, ResourceInline]


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "inn")
    list_display_links = ("id", "name")
    search_fields = ("name", "inn")
    list_filter = ()
    ordering = ("name",)
    readonly_fields = ()
    fieldsets = (
        (
            "Компания",
            {
                "fields": (
                    "name",
                    "inn",
                )
            },
        ),
    )


@admin.register(ProjectGoal)
class ProjectGoalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "project",
        "completion_date",
        "responsible",
        "is_done",
    )
    list_filter = ("is_done", "completion_date", "project")
    search_fields = (
        "title",
        "project__name",
        "responsible__username",
        "responsible__email",
    )
    list_select_related = ("project", "responsible")
    autocomplete_fields = ("project", "responsible")


@admin.register(ProjectNews)
class ProjectNewsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "datetime_created",
    )
    list_display_links = (
        "id",
        "project",
        "datetime_created",
    )
    # todo: set up admin panel for files
    filter_horizontal = ("files",)


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "project")


@admin.register(ProjectLink)
class ProjectLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "link", "project")
    list_display_links = ("id", "link", "project")


@admin.register(Collaborator)
class CollaboratorAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "project",
        "role",
        "datetime_created",
        "datetime_updated",
    )
    list_display_links = ("id", "user", "project")


@admin.register(DefaultProjectCover)
class DefaultProjectCoverAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "image",
        "datetime_created",
        "datetime_updated",
    )
    list_display_links = (
        "id",
        "datetime_created",
        "datetime_updated",
    )


@admin.register(DefaultProjectAvatar)
class DefaultProjectAvatarAdmin(admin.ModelAdmin):
    list_display = ("id", "image", "datetime_created")
