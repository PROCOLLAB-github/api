from django.contrib import admin

from news.models import News, NewsTag


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "tags_str")
    list_display_links = (
        "id",
        "title",
    )


@admin.register(NewsTag)
class NewsTagAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "datetime_created", "datetime_updated", "id")
    list_display_links = (
        "id",
        "name",
    )
