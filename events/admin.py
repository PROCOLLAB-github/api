from django.contrib import admin
from django import forms
from events.models import Event, LikesOnEvent


class EventAdminForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = "__all__"
        labels = {
            "title": "Название",
            "text": "Описание",
            "short_text": "Краткое описание",
            "cover_url": "URL обложки",
            "datetime_of_event": "Дата проведения",
            "datetime_created": "Дата создания",
            "datetime_updated": "Дата изменения",
            "tg_message_id": "ID поста в ТГ",
            "website_url": "URL от организатора",
            "event_type": "Формат проведения",
            "prize": "Награда",
            "registered_users": "Зарегистрированные пользователи",
            "views": "Просмотры",
            "likes": "Оценили",
            "tags": "Теги",
        }
        help_texts = {
            "title": "Обязателен к заполнению, max 256 символов",
            "text": "Описание мероприятия на сайт, обязаетльно к заполнению",
            "short_text": "Краткое описание для превью, 256 симв. макс., можно оставить пустым",
            "cover_url": "Ссылка на картинку для обложки мероприятия, обязательно",
            "datetime_of_event": "Дата проведения, обязательно",
            "website_url": "URL от организатора, обязательно",
            "event_type": "Формат проведения",
            "prize": "256 char, обязательно",
            "tags": "Указывать через запятую(можно использовать пробел в теге)",
        }


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    form = EventAdminForm
    save_as = True
    save_on_top = True
    filter_horizontal = ["registered_users", "favorites"]
    list_display = (
        "id",
        "title",
        "datetime_created",
    )
    list_display_links = (
        "id",
        "title",
        "datetime_created",
    )
    readonly_fields = (
        "tg_message_id",
        "views",
    )
    radio_fields = {"event_type": admin.VERTICAL}


@admin.register(LikesOnEvent)
class LikesOnEventAdmin(admin.ModelAdmin):
    list_display = ("id",)
    list_display_links = ("id",)
