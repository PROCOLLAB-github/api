# Статистика участников: селективный перенос в PROD

База: `master`, `1b2087787a1554733768a1984da12b0070c1ee05`.
Источник: DEV [#756](https://github.com/PROCOLLAB-github/api/pull/756),
merge `11f1e66a85e266d57fc6b0f8c080ee8cd0683f19`.

Перенесены только сериализатор, сервис агрегатов, публичный GET, маршрут и
тесты статистики. Merge-коммит DEV не включён в историю PROD-ветки.
Модели, миграции, React domain, зависимости и workflows не изменены.

## Контракт и доступ

`GET /auth/public-users/stats/` возвращает только четыре целых числа:

```json
{
  "total": 1248,
  "in_projects": 684,
  "in_programs": 214,
  "new_last_30_days": 63
}
```

Это пример контракта, а не реальные показатели PROD. Пустой каталог даёт
четыре нуля. Политика `AllowAny` сохранена из DEV #756. POST возвращает 405.
Ответ не содержит ID, email, телефонов, дат рождения, данных проектов или программ.
Поиск, skills, speciality и параметры пагинации игнорируются: агрегаты глобальные.

## Определения

Все метрики считают только активных legacy `CustomUser` с `user_type=MEMBER`.

| Поле | Условие |
| --- | --- |
| `total` | Все такие пользователи |
| `in_projects` | Человек является `Project.leader` или `Collaborator.user` хотя бы в одном проекте с `draft=false`, `is_public=true` |
| `in_programs` | Есть `PartnerProgramUserProfile` хотя бы одной программы с `draft=false` |
| `new_last_30_days` | `datetime_created >= timezone.now() - timedelta(days=30)`, граница включительна |

Один человек учитывается один раз независимо от числа связей и совмещения ролей.
Реализация использует `Exists` и `Count` внутри одного агрегирующего SQL-запроса.
Python-обходов пользователей и N+1 нет.

## Производительность

Тест считает SQL всего анонимного GET через `assertNumQueries(1)`; создание
данных выполняется за пределами замера.

| Активных MEMBER | SQL-запросов |
| ---: | ---: |
| 10 | 1 |
| 100 | 1 |
| 1000 | 1 |

Отдельный тест подтверждает один запрос при десяти проектах и десяти программах
одного человека. Это проверка числа запросов, а не нагрузочный benchmark PROD.

## Проверка

Использованы Python 3.11.15, PostgreSQL 18.1 и конфигурация
`procollab.settings_ci` с отдельной локальной тестовой базой
`test_procollab_prod_member_statistics`. SQLite не использовался.

Целевой модуль `users.tests.test_member_statistics_api`: **14 тестов прошли**.
Проверены пустой каталог, роли и активность, оба источника участия, дедупликация,
черновики и приватные проекты, программы, граница 30 суток, только четыре числа,
независимость от фильтров и постоянное число SQL-запросов.

С `NEXTGEN_SURFACE_ENABLED=False` выполнены статистика, quarantine и уведомления:
**30 тестов, OK (2 ожидаемых skip)**. Это подтверждает доступность статистики
в production-конфигурации с выключенной nextgen surface.

`manage.py check`, `makemigrations --check --dry-run`, Black пяти изменённых
Python-файлов, Flake8 всех отслеживаемых Python-файлов и двух новых модулей,
`git diff --check` прошли. Миграций нет.

### Полный PostgreSQL suite: ограничение проверки

Полный suite **не зелёный**. Оба запуска выполнили 1596 тестов:

| Запуск | Итог |
| --- | --- |
| `manage.py test --noinput --verbosity 2` | 2 ошибки, 3 skip; 880.988 s |
| `manage.py test --keepdb --noinput --verbosity 1` (режим CI) | 1 ошибка, 3 skip; 833.717 s |

Все ошибки — `TimeoutError` при `WebsocketCommunicator.receive_json_from()`
в неизменённых тестах чатов. В первом запуске:

- `chats.tests.test_project.DirectTests.test_delete_message_in_other_project_other_message`
- `chats.tests.test_project.DirectTests.test_edit_message_in_my_project_my_message`

Во втором:

- `chats.tests.test_direct.DirectTests.test_edit_other_message_in_other_chat`

Тесты статистики прошли в обоих полных запусках. Код и тесты `chats/`
совпадают с exact master. В первом запуске после тестов также не удалось удалить
тестовую БД из-за 21 оставшегося соединения; повтор использовал штатный режим CI
`--keepdb`. Исправления чатов или изменения таймаутов в этот перенос не включены.

Все три перечисленных теста затем прошли отдельно: **3/3 на exact master** и
**3/3 в ветке переноса**. Это указывает на нестабильность при полном локальном
прогоне, но не заменяет его зелёный результат. Ограничение сохранено в draft PR.

## Согласование с Angular

Источник интерфейса — DEV #381. Angular получает данные через adapter → repository
→ use-case → facade. Desktop sidebar остаётся 157 px, мобильная статистика стоит
после controls и перед списком. Скриншоты и точные измерения находятся в
[Angular draft PR #382](https://github.com/PROCOLLAB-github/procollab/pull/382).
В нём карточка на desktop измерена как 157 × 280 px, overflow равен нулю
на 1440/1280/1024/768/414/390/375 px. React не изменён.
