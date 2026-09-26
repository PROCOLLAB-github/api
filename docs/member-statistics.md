# Статистика каталога участников

## Контракт и доступ

`GET /auth/public-users/stats/` возвращает только четыре целых неотрицательных числа:

```json
{
  "total": 1248,
  "in_projects": 684,
  "in_programs": 214,
  "new_last_30_days": 63
}
```

Доступ `AllowAny` совпадает с существующим `/auth/public-users/`.
Идентификаторы, персональные данные, проекты и программы не сериализуются.
GET не изменяет данные. Другие методы не добавлены.

Это глобальная статистика, независимая от выдачи каталога. Endpoint не поддерживает
фильтры: `fullname`, `skills__contains`, `speciality__icontains`, `offset`, `limit`
и прочие query-параметры игнорируются, а не передаются в ORM.

## Определения

Общая выборка: legacy `CustomUser`, `user_type=MEMBER`, `is_active=True`.

| Поле | Правило |
| --- | --- |
| `total` | Число пользователей общей выборки |
| `in_projects` | Число людей, для которых существует `Project.leader` либо `Collaborator.user` в проекте с `draft=False`, `is_public=True` |
| `in_programs` | Число людей с `PartnerProgramUserProfile` для программы с `draft=False` |
| `new_last_30_days` | Число людей с `datetime_created >= timezone.now() - timedelta(days=30)`; граница включительна |

Несколько проектов, пересечение ролей leader/collaborator и несколько программ
не увеличивают счётчик одного человека. При пустой выборке все значения равны нулю.
Наличие `is_staff` само по себе не заменяет правило `user_type=MEMBER`.

## Реализация и стоимость

`users.services.member_statistics.get_member_statistics()` строит одну агрегирующую
SQL-команду с тремя коррелированными `EXISTS`. Основная таблица пользователей не
соединяется с коллекциями, поэтому размножения строк и циклов по людям нет.
Сериализатор получает уже вычисленные четыре числа.

Тесты подтверждают **1 SQL-запрос** для анонимного GET при 10, 100 и 1000 пользователях,
а также при множественных связях проектов и программ. Это контроль количества
запросов, не нагрузочный тест времени выполнения на production-объёмах.

## Проверки 27.09.2026

База DEV: `caea57a7c6f2869e7f2522e37c8fc395569b030c`.
Локальный PostgreSQL 18, отдельная тестовая БД; секреты настроек не входят в репозиторий.
Полный suite запускался с `NEXTGEN_SURFACE_ENABLED=True`, чтобы проверить сохранение
существующих контрактов React-домена, без изменения его кода.

- `manage.py test users.tests.test_member_statistics_api users.tests.test_user_lists_api --noinput --keepdb`: **25 OK**.
- `manage.py test --noinput --keepdb`: **901 OK**, 264.845 с.
- `manage.py check`: 0 issues.
- `manage.py makemigrations --check --dry-run`: No changes detected.
- `black --check` и `flake8` для пяти затронутых Python-файлов: exit 0.
- `git diff --check`: exit 0.

Миграций, зависимостей и изменений workflows нет. React, поиск fullname и правила
участия не изменены. Для будущего DEV-развёртывания endpoint нужен Angular-виджету;
старый frontend продолжает использовать прежний список. Merge/deploy не выполнялись.
