from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from news.models import News
from partner_programs.models import PartnerProgram


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    # todo
    list_display = (
        "id",
        "content_type",
        "object_id",
        "text",
        "datetime_created",
        "datetime_updated",
    )
    list_display_links = (
        "id",
        "content_type",
        "object_id",
        "text",
        "datetime_created",
        "datetime_updated",
    )
    list_filter = (
        "datetime_created",
        "datetime_updated",
    )
    search_fields = ("text",)
    readonly_fields = (
        "datetime_created",
        "datetime_updated",
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[News]:
        qs = super().get_queryset(request)
        if "Руководитель программы" in request.user.groups.all().values_list(
            "name", flat=True
        ):
            user_programs_ids: list[int] = PartnerProgram.objects.filter(
                experts=request.user.expert
            ).values_list("id", flat=True)
            qs = qs.filter(
                object_id__in=user_programs_ids,
                content_type__model="PartnerProgram".lower(),
            )
        return qs

    # fieldsets = (
    #     (
    #         None,
    #         {
    #             "fields": (
    #                 "content_type",
    #                 "object_id",
    #                 "text",
    #                 "files",
    #             )
    #         },
    #     ),
    #     (
    #         "Даты",
    #         {
    #             "fields": (
    #                 "datetime_created",
    #                 "datetime_updated",
    #             )
    #         },
    #     ),
    # )
    # filter_horizontal = (
    #     "files",
    # )
    # save_on_top = True
