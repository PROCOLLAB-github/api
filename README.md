# Procollab Backend

Backend API для продукта Procollab.

## Стек

- Python
- Django
- Django REST Framework
- Channels
- Celery
- PostgreSQL
- Redis

## Базовые команды

Используются Python 3.11, Poetry 2.5.1 и PostgreSQL 14 или новее.

```bash
poetry install --no-root
poetry run python manage.py migrate
poetry run python manage.py runserver
poetry run python manage.py test
```

## Документация

- [Навигация по документации](docs/readme.md)
- [Разработка](docs/development.md)
- [Архитектура](docs/architecture.md)
- [API](docs/api.md)
- [Инфраструктура и деплой](docs/devops-state.md)
- [Подготовка обновления зависимостей prod](docs/prod-dependencies-20261103.md)
- [Доменные модули](docs/modules/readme.md)
