# Аналитика партнёрской программы

## Endpoint и доступ

`GET /programs/<program_id>/manager-overview/`

Endpoint доступен менеджерам указанной программы, staff и superuser. Для
авторизованного пользователя без этих прав возвращается `403`, для неизвестной
программы — `404`, для anonymous — `401`. Тот же `can_manage_program`
используется обоими read-only drilldown endpoints ниже. Эксперт программы без
прав менеджера доступа не получает. POST/PATCH/PUT/DELETE не поддерживаются.

## Контракт

```json
{
  "summary": {
    "participants": {"total": 3},
    "projects": {"total": 2},
    "experts": {"total": 2},
    "regions": {
      "total": 1,
      "items": [{"name": "Москва", "count": 2}]
    },
    "participant_regions": {
      "total": 2,
      "items": [
        {"name": "Москва", "count": 2},
        {"name": "Набережные Челны", "count": 1}
      ]
    }
  },
  "participant_funnel": {
    "registrations": 4,
    "unique_participants": 3,
    "with_team": 2,
    "project_creators": 1,
    "submitted_project_creators": 1
  },
  "solution_funnel": {
    "created": 2,
    "not_submitted": 0,
    "submitted": 2,
    "evaluated": 1
  },
  "evaluation_status": {
    "mode": "distributed",
    "max_evaluations_per_project": 2,
    "assignments": {"total": 3, "pending": 1, "evaluated": 2},
    "projects": {
      "submitted": 2,
      "awaiting_evaluation": 0,
      "partially_evaluated": 1,
      "evaluated": 1
    }
  },
  "attention": {
    "participants_without_team": 1,
    "projects_awaiting_evaluation": 1,
    "delayed_experts": {"total": 0, "items": []}
  },
  "activity": [
    {
      "date": "2026-08-01",
      "registrations": 2,
      "submitted_solutions": 1
    }
  ]
}
```

## Семантика метрик

- `registrations` — количество регистрационных записей
  `PartnerProgramUserProfile`, включая сохранённые записи с удалённым
  пользователем.
- `unique_participants` и `summary.participants.total` — уникальные ненулевые
  `PartnerProgramUserProfile.user_id`.
- Участник считается состоящим в команде, если он является руководителем либо
  `Collaborator` проекта, связанного с программой через
  `PartnerProgramProject`. Поле `PartnerProgramUserProfile.project` не
  используется как единственный источник состава команды.
- `project_creators` — уникальные зарегистрированные участники, являющиеся
  руководителями связанных с программой проектов.
- Решение программы — `PartnerProgramProject`. Состояние сдачи определяется
  только его полями `submitted` и `datetime_submitted`.
- `max_evaluations_per_project` возвращает `PartnerProgram.max_project_rates`:
  это верхний лимит числа оценивающих экспертов, а не обязательное количество
  оценок. Значение может быть `null` и не определяет статус проекта.
- В открытом режиме (`mode=open`) назначения не обязательны. Сданный проект
  считается оценённым после первой оценки любого уникального эксперта по
  критериям программы; до первой оценки он ожидает оценивания.
- В распределённом режиме (`mode=distributed`) ожидаемые оценки определяются
  `ProjectExpertAssignment`. Проект без назначений либо без выполненных
  назначений ожидает оценивания; проект с частью выполненных назначений имеет
  статус `partially_evaluated`; при выполнении всех назначений — `evaluated`.
- Назначение считается выполненным только после сдачи проекта и заполнения
  **всех критериев текущей программы** назначенным экспертом. Наличие одной
  оценки больше не означает завершение назначения (см. статусы ниже).
- В открытом режиме `projects_awaiting_evaluation` включает только сданные
  проекты без оценки. В распределённом режиме он включает ожидающие и частично
  оценённые проекты.
- `summary.experts.total` — число уникальных `Expert`, состоящих в программе
  через `Expert.programs`, независимо от наличия назначений.
- Регионы строятся по непустому `Project.region` связанных проектов. Пробелы по
  краям удаляются; `items` сортируется по убыванию количества, затем по имени.
- `summary.participant_regions` строится по `User.city` той же группы уникальных
  ненулевых пользователей программы, что используется для
  `summary.participants.total`. Пустые и состоящие только из пробелов значения
  исключаются. Пробелы по краям удаляются; одинаковые после этого строки
  группируются, а `items` сортируется по убыванию количества, затем по имени.
  Значения не приводятся к другому регистру, не исправляются и не сопоставляются
  с каноническими регионами: legacy-строки остаются отдельными элементами.
- `activity` всегда содержит последние 30 календарных дней, включая текущий.
  Пропущенные даты заполняются нулями. Регистрации группируются по
  `PartnerProgramUserProfile.datetime_created`, сдачи — по
  `PartnerProgramProject.datetime_submitted`.

## Кейсы

В текущей модели нет отдельной сущности или обязательной связи «кейс».
Произвольные `PartnerProgramField` могут иметь похожее название, но не являются
стабильным системным контрактом. Поэтому `cases` в ответ не добавляется.
Для такой аналитики нужна отдельная модель кейса и явная внешняя связь
`PartnerProgramProject` с выбранным кейсом либо утверждённое системное поле с
гарантированным идентификатором.

## Статусы назначений и проектов

Источники истины: `ProjectExpertAssignment` (программа × проект × эксперт),
`ProjectScore` (критерий × пользователь эксперта × проект), `Criteria` программы,
`PartnerProgramProject.submitted` / `datetime_submitted` и дата создания назначения.
Модели, запись оценок и поведение сдачи проекта не меняются.

`criteria_total` — число критериев программы. `criteria_scored` — число DISTINCT
критериев этой программы, по которым существует строка оценки именно этого
пользователя и проекта. Оценки другой программы/эксперта/проекта не учитываются.
Строка со значением `"0"` или пустым/nullable значением считается существующей
оценкой; аналитика не вводит новую валидацию `ProjectScore.value`.
Создаваемый текущим signal критерий «Комментарий» типа `str` также входит в
общее число критериев: исключения по названию или типу не вводятся.

| Условие | status |
| --- | --- |
| Проект не сдан в этой программе | `not_ready` |
| Сдан, критериев нет или оценено 0 критериев | `pending` |
| Сдан, 0 < оценено < всего критериев | `in_progress` |
| Сдан, всего > 0 и оценено >= всего | `completed` |

Старые имена полей `evaluation_status.assignments` сохраняются:
`total` — все реальные назначения, `evaluated` — только `completed`,
`pending` — `not_ready` + `pending` + `in_progress`.
Всегда `total = evaluated + pending`.

Для сданного проекта в distributed-режиме:

- `awaiting_evaluation`: нет назначений или ни одно не завершено;
- `partially_evaluated` («Частично оценено»): хотя бы один назначенный эксперт
  завершил все критерии, но не все назначения завершены;
- `evaluated`: назначений больше нуля и все они завершены.

Частичное заполнение критериев без завершённого эксперта само по себе не даёт
проекту статус «Частично оценено». В open-режиме прежняя семантика проекта
сохранена: первая оценка по критерию программы достаточна; фиктивные назначения
из оценок не создаются.

## Список назначений

`GET /programs/<program_id>/manager-overview/assignments/?scope=all`

Ответ `200` — JSON-массив, без пагинационной обёртки; пустой результат `[]`.
Стабильная сортировка по `assignment_id` по возрастанию.
`scope` допускает только `all` (по умолчанию), `completed`, `pending`.
`pending` включает все незавершённые статусы, в том числе `not_ready`.
Неизвестное или пустое значение — `400` с ошибкой поля `scope`.
В open-режиме возвращаются только физически существующие назначения.

Пример при времени запроса `2026-09-05T00:00:00Z`:

```json
[
  {
    "assignment_id": 17,
    "expert": {
      "expert_id": 4,
      "user_id": 123,
      "first_name": "Иван",
      "last_name": "Иванов",
      "full_name": "Иван Иванов",
      "avatar": null
    },
    "project": {"id": 55, "name": "Проект А"},
    "status": "in_progress",
    "criteria_total": 3,
    "criteria_scored": 1,
    "assigned_at": "2026-09-03T10:00:00Z",
    "project_submitted": true,
    "project_submitted_at": "2026-09-03T12:00:00Z",
    "waiting_since": "2026-09-03T12:00:00Z",
    "waiting_seconds": 129600
  }
]
```

`expert` — явный allow-list, без email/телефона/auth-полей. `avatar` — URL или
`null`, `full_name` — имя и фамилия через пробел (пустые части пропускаются).
Даты — ISO 8601 в настроенной Django timezone; `Z` в примерах означает UTC.

### Время ожидания

Для submitted + non-completed:
`waiting_since = max(datetime_submitted, assignment.datetime_created)`;
`waiting_seconds = max(0, floor((now - waiting_since).total_seconds()))`.
В одном ответе используется один `now` для всех назначений.

Для `not_ready`: `project_submitted_at`, `waiting_since`, `waiting_seconds` —
`null`. Для `completed` оба поля ожидания — `null`, дата сдачи сохранена.
Если у legacy-сданного проекта `datetime_submitted=null`, статус рассчитывается
обычно, но ожидание остаётся `null`: достоверного начала SLA нет. Такая запись
не объявляется просроченной. Дата создания проекта никогда не подставляется.
Будущая дата даёт 0 секунд ожидания и не создаёт просрочку.

## Оценки назначения

`GET /programs/<program_id>/manager-overview/assignments/<assignment_id>/scores/`

Ответ `200` — **все поля элемента списка выше**, плюс массив `scores`.
Назначение ищется только внутри указанной программы; чужое/несуществующее —
`404`, даже если менеджер управляет обеими программами.

Например к элементу `17` выше добавляется:

```json
{
  "scores": [
    {
      "criterion_id": 1,
      "name": "Новизна",
      "description": "Оцените новизну решения",
      "type": "int",
      "min_value": 0,
      "max_value": 10,
      "value": "0",
      "is_scored": true
    },
    {
      "criterion_id": 2,
      "name": "Реализуемость",
      "description": null,
      "type": "int",
      "min_value": 0,
      "max_value": 10,
      "value": null,
      "is_scored": false
    },
    {
      "criterion_id": 3,
      "name": "Комментарий",
      "description": null,
      "type": "str",
      "min_value": null,
      "max_value": null,
      "value": null,
      "is_scored": false
    }
  ]
}
```

Возвращаются все критерии программы по возрастанию `criterion_id`.
`value` сохраняет строковый/nullable контракт модели без преобразования чисел
или обрезки пробелов. `is_scored` означает наличие строки `ProjectScore`:
он отличает отсутствие оценки от существующей строки с `value=null`.

## Требует внимания: задержки экспертов

`attention.delayed_experts = {"total": <число экспертов>, "items": [...]}`.
Существующие `participants_without_team` и `projects_awaiting_evaluation`
сохраняются. В open-режиме всегда `{"total": 0, "items": []}`.

SLA учитывает только сданные, незавершённые назначения с известным наступившим
`waiting_since`:

- `warning`: минимум 2 назначения ждут каждое >= 24 часов;
- `critical`: хотя бы 1 назначение ждёт >= 48 часов (имеет приоритет).

Один проект, ожидающий 25 часов, не даёт предупреждение. Выполненные,
несданные, будущие и назначения другой программы не создают просрочку.
`assignments_total`, `completed`, `pending` включают все реальные назначения
эксперта текущей программы, включая несданные в `pending`.

```json
{
  "total": 1,
  "items": [
    {
      "expert_id": 4,
      "user_id": 123,
      "first_name": "Иван",
      "last_name": "Иванов",
      "full_name": "Иван Иванов",
      "avatar": null,
      "assignments_total": 8,
      "completed": 2,
      "pending": 6,
      "overdue_24h": 4,
      "overdue_48h": 1,
      "oldest_waiting_since": "2026-09-02T20:00:00Z",
      "oldest_waiting_seconds": 187200,
      "severity": "critical"
    }
  ]
}
```

Сортировка: critical перед warning, затем большее время ожидания, затем
`expert_id` по возрастанию. Старейшее ожидание берётся среди незавершённых
сданных назначений с известной датой, а не по дате создания проекта.

## Производительность и границы

Прогресс, дата сдачи и безопасные поля пользователя/проекта выбираются одним
SQL SELECT: связанные таблицы через JOIN, число критериев и DISTINCT-оценок —
через Subquery/Count; связь проекта с программой также через Subquery.
Нет запросов из сериализаторов и отдельных SQL-запросов в цикле назначений.
Сводка повторно использует тот же список для счётчиков проектов и SLA.
Score drilldown добавляет два фиксированных запроса (критерии и оценки пары).

Regression query budget для manager с уже аутентифицированным request.user:
список — 3 SQL, overview — 10 SQL, scores — 5 SQL; не растёт при переходе
от 1 к 31 назначению. JWT/session-аутентификация может добавить свои запросы.
Проверяются SQLite и PostgreSQL; новых моделей, индексов и миграций нет.
