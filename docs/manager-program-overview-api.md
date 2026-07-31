<!-- Roadmap: DEV-076, DEV-056 -->

# Manager program overview API

DEV-076 является первым read-only этапом DEV-056 «Кабинет менеджера». Endpoint
возвращает компактные обезличенные счетчики по пути участника от регистрации до
экспертной оценки.

## Endpoint и права

```http
GET /programs/<program_id>/manager-overview/
```

Требуется авторизация. Доступ разрешен manager указанной `PartnerProgram`, staff
и superuser. Обычный участник и manager другой программы получают `403`.
Несуществующая программа возвращает `404`.

## Контракт

```json
{
  "program": {"id": 1, "name": "Program"},
  "registrations": {"total": 0},
  "applications": {
    "total": 0,
    "by_status": {
      "draft": 0,
      "submitted": 0,
      "approved": 0,
      "rejected": 0,
      "withdrawn": 0,
      "cancelled": 0
    },
    "by_participation_mode": {
      "undecided": 0,
      "individual": 0,
      "team": 0
    }
  },
  "teams": {"total": 0, "accepted_members": 0},
  "submissions": {
    "total": 0,
    "by_status": {
      "draft": 0,
      "submitted": 0,
      "returned": 0,
      "final": 0,
      "cancelled": 0
    },
    "applications_with_submitted_solution": 0
  },
  "expert_assignments": {
    "total": 0,
    "by_status": {"assigned": 0, "completed": 0, "revoked": 0}
  },
  "evaluations": {
    "total": 0,
    "by_status": {"draft": 0, "submitted": 0}
  }
}
```

Отсутствующие статусы всегда присутствуют в ответе с нулевым значением.

## Семантика счетчиков

- `registrations.total` — количество `PartnerProgramUserProfile` программы.
- `applications.total` и `by_status` — заявки программы целиком и по статусам.
- `applications.by_participation_mode` — заявки по режимам `undecided`,
  `individual` и `team`.
- `teams.total` — команды, связанные с заявками программы.
- `teams.accepted_members` — только `TeamMember` со статусом `accepted`, включая
  капитана. Исторические и ожидающие статусы не учитываются.
- `submissions.total` и `by_status` — все версии `Submission` программы.
- `applications_with_submitted_solution` — число уникальных заявок, имеющих хотя
  бы одну версию `Submission` в статусе `submitted` или `final`.
- `expert_assignments` — назначения через `Submission` программы целиком и по
  статусам `assigned`, `completed`, `revoked`.
- `evaluations` — оценки через `Submission` программы целиком и по статусам
  `draft`, `submitted`.

Подсчеты выполняются фиксированным набором ORM aggregate-запросов и не зависят
от количества участников.

## Ограничения данных

Ответ не содержит email, ФИО, `form_data`, `partner_program_data`, ссылки на
пользовательские файлы, содержимое решений, комментарии экспертов и scores
отдельных пользователей.

Списки и фильтры сущностей, просмотр анкет, выгрузки Excel/CSV, результаты,
рейтинг, уведомления, продуктовая аналитика и frontend в DEV-076 не входят.
Endpoint не изменяет заявки, решения, назначения или оценки.

Roadmap-Complete: DEV-076

Roadmap-Partial: DEV-056
