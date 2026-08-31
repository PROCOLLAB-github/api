# Аналитика партнёрской программы

## Endpoint и доступ

`GET /programs/<program_id>/manager-overview/`

Endpoint доступен менеджерам указанной программы, staff и superuser. Для
авторизованного пользователя без этих прав возвращается `403`, для неизвестной
программы — `404`.

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
    "required_evaluations_per_project": 2,
    "assignments": {"total": 3, "pending": 1, "evaluated": 2},
    "projects": {
      "submitted": 2,
      "awaiting_first_evaluation": 0,
      "requiring_additional_evaluations": 1,
      "evaluated": 1
    }
  },
  "attention": {
    "participants_without_team": 1,
    "projects_awaiting_evaluation": 1
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
- Проект считается оценённым, когда число уникальных пользователей с
  `ProjectScore` по критериям программы достигает `max_project_rates`. Если
  `max_project_rates` не задан, требуется одна оценка.
- Назначение считается оценённым, если назначенный эксперт сохранил хотя бы
  один `ProjectScore` этого проекта по критерию текущей программы.
- `projects_awaiting_evaluation` включает сданные проекты без первой оценки и
  сданные проекты, которым не хватает оценок до настроенного количества.
- `summary.experts.total` — уникальные `expert_id` в
  `ProjectExpertAssignment`, а не количество назначений.
- Регионы строятся по непустому `Project.region` связанных проектов. Пробелы по
  краям удаляются; `items` сортируется по убыванию количества, затем по имени.
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
