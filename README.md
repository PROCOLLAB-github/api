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

```bash
poetry install --no-root
poetry run python manage.py migrate
poetry run python manage.py runserver
poetry run python manage.py test
```

## Документация

- [Навигация по документации](docs/readme.md)
- [Разработка](docs/development.md)
- [Обновление зависимостей до Django 5.2 LTS](docs/dependency-upgrade-20261102.md)
- [Архитектура](docs/architecture.md)
- [API](docs/api.md)
- [Инфраструктура и деплой](docs/devops-state.md)
- [Доменные модули](docs/modules/readme.md)
