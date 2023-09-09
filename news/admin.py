from django.contrib import admin

from news.models import News


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
