# Перенос поиска участников в PROD

База master: `24fb95169b59eea08ee3bd2e755010cd4d232211`.
Источник: DEV #754, `98e4e3bcf7149be1b0dc5d03840fd8f894a2b534` (merge `caea57a7c6f2869e7f2522e37c8fc395569b030c`).

Перенесены только фильтр fullname и его API-тесты. До переноса оба файла master совпадали с родителем source-коммита. Runtime-реализация совпадает с source; дополнительно проверены обязательность обеих частей имени, фрагмент фамилии и буквальное совпадение имени с regex-символами.

## Контракт

`GET /auth/public-users/?fullname=...` ищет фрагмент имени или фамилии. Для нескольких слов проверяются границы между именем и фамилией в обоих порядках; обе стороны AND-условия обязательны. Пробелы нормализуются. Пустой ввод не ограничивает выдачу. Составные имена сохраняются.

На PostgreSQL с ограниченным LC_CTYPE кириллический icontains не гарантирует поиск без учёта регистра. Фильтр строит буквальный regex из экранированных символов с явными вариантами Unicode-регистра. Пользователь не задаёт операторы регулярного выражения. Длина ограничивается суммой максимальных длин двух полей; более длинный запрос сразу даёт пустую выдачу. Фильтрация остаётся в SQL до пагинации.

UserFilter является общим: его fullname также используется административным списком пользователей. Permissions, serializers, pagination, user_type и остальные фильтры не менялись. React, миграции, зависимости, workflows и DEV-ветка не изменялись.

## Проверки

Локально: Python 3.11, PostgreSQL 18, конфигурация `procollab.settings_ci` с отдельной локальной тестовой БД и без внешних сервисов. Пароли и локальные настройки не входят в PR.

- `python manage.py test users.tests.test_user_lists_api --noinput --keepdb --verbosity 1`: 13 тестов, OK.
- `python manage.py check`: 0 issues.
- `python manage.py makemigrations --check --dry-run`: No changes detected.
- `python -m black --check users/filters.py users/tests/test_user_lists_api.py`: OK.
- `python -m flake8 users/filters.py users/tests/test_user_lists_api.py`: OK.
- `git diff --check`: OK.

Результат полного PostgreSQL suite и нового GitHub PostgreSQL CI указан в описании PR. Предыдущий DEV-run не считается проверкой этого PROD-переноса. Live PROD до deploy не проверялся: безопасная авторизованная браузерная сессия отсутствует.
