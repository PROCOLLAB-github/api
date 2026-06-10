# Core

## Назначение

Модуль `core` содержит общие сущности и инфраструктурные helper'ы, которые
переиспользуются другими доменными модулями Procollab.

В модуле находятся:

- generic-модели лайков, просмотров и ссылок;
- справочники навыков и специализаций;
- generic-связи навыков и специализаций с объектами;
- REST endpoints справочника навыков;
- общие serializers, permissions и pagination;
- helpers для Excel-выгрузок;
- cache-ключи онлайна пользователей;
- WebSocket JWT middleware;
- logging middleware.

## Статус модуля

`core` подключен в публичный API через `/core/`, но публичная API-поверхность
сейчас ограничена endpoints навыков.

Модуль является shared-слоем: изменения в нем могут затронуть `users`,
`projects`, `news`, `feed`, `vacancy`, `partner_programs`, `courses`,
`project_rates`, `metrics` и `chats`.

Собственных тестов у `core` сейчас нет. Часть поведения косвенно покрывается
тестами зависимых модулей.

## Основные возможности

- хранение generic-лайков через `Like`;
- хранение generic-просмотров через `View`;
- хранение generic-ссылок через `Link`;
- справочник навыков `SkillCategory` / `Skill`;
- generic-привязка навыков через `SkillToObject`;
- справочник специализаций `SpecializationCategory` / `Specialization`;
- generic-привязка специализаций через `SpecializationToObject`;
- получение навыков nested-списком по категориям;
- получение навыков плоским paginated-списком с фильтром по названию;
- подготовка XLSX-файлов в памяти;
- безопасная подготовка имени файла и значений Excel-ячеек;
- построение download-response для XLSX;
- формирование ключей online-cache;
- JWT-аутентификация WebSocket через subprotocol;
- перехват стандартного logging в loguru.

## Архитектура

- `core/models.py` - generic-модели, навыки и специализации.
- `core/views.py` - API справочника навыков.
- `core/serializers.py` - serializers навыков и общие request serializers.
- `core/services.py` - лайки, просмотры, ссылки и Base64 image encoder.
- `core/utils.py` - email helper, online-cache keys и Excel helpers.
- `core/permissions.py` - общие permissions.
- `core/pagination.py` - общий limit/offset pagination.
- `core/filters.py` - фильтр навыков.
- `core/fields.py` - кастомное поле списка для comma-separated значений.
- `core/auth/middleware.py` - WebSocket JWT auth middleware.
- `core/log/` - интеграция стандартного logging с loguru.
- `core/admin.py` - Django admin для core-сущностей.

## Ключевые сущности

- `Like` - generic-лайк пользователя к объекту через `ContentType`.
- `View` - generic-просмотр пользователя к объекту через `ContentType`.
- `Link` - generic-ссылка, привязанная к объекту через `ContentType`.
- `SkillCategory` - категория навыка.
- `Skill` - навык внутри категории.
- `SkillToObject` - generic-связь навыка с пользователем, вакансией, проектом
  или другим объектом.
- `SpecializationCategory` - категория специализации.
- `Specialization` - специализация внутри категории.
- `SpecializationToObject` - generic-связь специализации с объектом.

## API

- `GET /core/skills/nested/` - категории навыков со вложенным списком навыков.
- `GET /core/skills/inline/` - плоский список навыков с pagination.

Фильтр для `/core/skills/inline/`:

- `name__icontains` - поиск навыка по части названия.

Pagination:

- `limit`, по умолчанию `10`;
- `offset`.

Справочник специализаций физически хранится в `core`, но endpoints находятся в
модуле `users`:

- `GET /auth/users/specializations/nested/`;
- `GET /auth/users/specializations/inline/`.

## Основные сценарии

### 1. Фронт получает справочник навыков

Для отображения навыков по категориям используется:

```text
GET /core/skills/nested/
```

Для поиска и autocomplete используется:

```text
GET /core/skills/inline/?name__icontains=python
```

### 2. Модуль привязывает навыки к объекту

Доменные модули создают `SkillToObject` через `ContentType`.

Например:

- `users` хранит навыки пользователя;
- `vacancy` хранит требуемые навыки вакансии;
- serializers используют `SkillToObjectSerializer` для единого response
  формата навыка.

### 3. Модуль фиксирует лайк или просмотр

`core.services` предоставляет функции:

- `set_like(obj, user, is_liked)`;
- `add_like(obj, user)`;
- `remove_like(obj, user)`;
- `is_fan(obj, user)`;
- `get_likes_count(obj)`;
- `set_viewed(obj, user, is_viewed)`;
- `add_view(obj, user)`;
- `remove_view(obj, user)`;
- `is_viewer(obj, user)`;
- `get_views_count(obj)`.

Эти функции используются в `news`, `feed`, `partner_programs`,
`project_rates` и других местах, где нужен generic-счетчик.

Важно: не все лайки в проекте уже переведены на generic-модель `core.Like`.
Например, у проектов и мероприятий еще есть отдельные legacy-модели лайков.

### 4. Модуль формирует XLSX-выгрузку

Для выгрузок используются:

- `XlsxFileToExport`;
- `sanitize_excel_value`;
- `build_xlsx_download_response`.

Эти helpers применяются в `partner_programs`, `project_rates`, `courses`,
`users` и `vacancy`.

### 5. WebSocket подключение проходит JWT-аутентификацию

`TokenAuthMiddleware` подключен в `procollab/asgi.py`.

Он ожидает WebSocket subprotocols в формате:

```text
["Bearer", "<JWT>"]
```

После проверки JWT middleware записывает пользователя в `scope["user"]`.
Этим пользуется `chats.ChatConsumer`.

### 6. Чаты обновляют online-cache

`core.utils` содержит функции:

- `get_user_online_cache_key(user)`;
- `get_users_online_cache_key()`.

`chats` пишет в эти ключи при подключении и отключении пользователя, а
`metrics` читает aggregate-ключ для отображения количества пользователей онлайн.

## Связи с другими модулями

- `users` - навыки, специализации, online-флаги, Excel-выгрузки и permissions.
- `vacancy` - required skills через `SkillToObject`, admin inline и выгрузки.
- `projects` - общие serializers/permissions, счетчики просмотров, online
  данные пользователей.
- `news` - generic likes/views.
- `feed` - generic likes/views для записей ленты.
- `partner_programs` - generic likes/views и Excel-выгрузки.
- `project_rates` - счетчики просмотров проектов и выгрузки.
- `courses` - Excel-выгрузка результатов.
- `chats` - WebSocket auth и online-cache keys.
- `metrics` - чтение online-cache.
- `industries` и `events` - переиспользуют общие permissions.

## Ограничения и риски

- У `core` нет собственных тестов; shared-поведение проверяется в основном
  косвенно через другие модули.
- `remove_link()` в `core.services` фильтрует `Like`, а не `Link`; это выглядит
  как баг.
- `get_views_count()` кеширует значение, но `add_view()` / `remove_view()` не
  инвалидируют кеш.
- `get_likes_count()` не использует кеш, хотя `LIKES_CACHING_TIMEOUT` объявлен.
- `Skill`, `SkillCategory`, `Specialization` и `SpecializationCategory` не имеют
  уникальности по `name`.
- `SkillToObject` и `SpecializationToObject` не ограничивают дубли на уровне
  модели.
- `Base64ImageEncoder.get_encoded_base64_from_url()` использует `urlopen` без
  timeout.
- `TokenAuthentication.authenticate()` не обрабатывает отсутствие пользователя
  после декодирования JWT.
- `CustomLoguruMiddleware` пишет логи в директорию `log/` внутри `BASE_DIR`;
  окружение должно гарантировать доступность этой директории.
- `CustomListField` преобразует список в строку через запятую и обратно; формат
  подходит не для всех типов значений.

## Тесты

Собственных тестов у модуля сейчас нет:

```text
DEBUG=True .venv/bin/python manage.py test core
```

Текущий запуск находит `0` тестов.

Поведение `core` частично покрывается тестами зависимых модулей:

- `news` и `feed` проверяют generic likes/views;
- `vacancy` и `users` проверяют работу навыков;
- `metrics` проверяет online-cache keys;
- `partner_programs`, `project_rates`, `courses` проверяют Excel-выгрузки через
  общие helpers.
