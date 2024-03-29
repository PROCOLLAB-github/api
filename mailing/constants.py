def get_default_mailing_schema() -> dict[str, dict[str, str]]:
    return {
        "title": {
            "title": "Заголовок письма",
            "default": "Рассылка | Procollab",
        },
        "text": {"title": "Основной текст письма"},
        "button_text": {"title": "Текст кнопки", "default": "Кнопка"},
    }


MAILING_USERS_BATCH_SIZE = 100
