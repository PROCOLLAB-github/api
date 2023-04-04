from django.contrib import admin
from django import forms
from events.models import Event


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
            "tags": "Теги"
        }
        help_texts = {
            "title": "Название мероприятия...",
            "text": "Описание мероприятия на сайт",
            "short_text": "Краткое описание для превью",
            "cover_url": "Ссылка на картинку для обложки мероприятия",
            "datetime_of_event": "Дата проведения",
            "website_url": "URL от организатора",
            "event_type": "Формат проведения",
            "tags": "Указывать через запятую(можно использовать пробел в теге)"
        }


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    form = EventAdminForm
    save_as = True
    save_on_top = True
    filter_horizontal = ["registered_users", "favorites", "likes"]
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
        "likes",
    )
    radio_fields = {"event_type": admin.VERTICAL}
