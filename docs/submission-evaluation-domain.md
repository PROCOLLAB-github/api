# Submission Evaluation Domain RFC

Статус: proposal.

Документ описывает следующий этап React-контура PROCOLLAB: назначение
экспертов на конкретные `Submission`, кабинет эксперта и управляемую отправку
оценки. RFC является только анализом. Он не меняет модели, миграции,
serializers, views, permissions, API, admin, settings или deploy.

Главное правило:

> Эксперт оценивает зафиксированную `Submission`, а не изменяемый legacy
> `Project`.

## 1. Текущее состояние

### Реализованный React-контур

В `partner_programs` уже существуют:

- `Application` для индивидуального или командного участия;
- `Team`, `TeamMember` и `TeamInvite`;
- `Submission` с версиями, `stage_key` и статусами `draft`, `submitted`,
  `returned`, `final`, `cancelled`;
- Submission API:
  - `GET/POST /applications/<application_id>/submissions/`;
  - `GET/PATCH /submissions/<submission_id>/`;
  - `POST /submissions/<submission_id>/submit/`;
  - `POST /submissions/<submission_id>/cancel/`;
- owner/captain, accepted-team-member, manager и staff permissions.

`Submission` хранит решение независимо от `Project`. Уникальность версии уже
защищена по `application + stage_key + version`. Экспертного доступа к
Submission и нового Evaluation API пока нет.

### Аудит legacy evaluation

| Область | Текущая реализация | Вывод для нового контура |
|---|---|---|
| Критерии | `project_rates.Criteria`: Program, имя, описание, тип `str/int/float/bool`, числовые границы | Можно временно использовать как каталог критериев Program, но не как готовую схему Evaluation |
| Оценка | `ProjectScore`: FK на Criteria, User и Project, строковое `value` | Не переиспользовать: оценивает Project, не имеет формы, статуса, комментария и времени финальной отправки |
| Уникальность | `criteria + user + project` | Не защищает `submission + expert` и не моделирует атомарную отправку формы |
| Валидация | `ProjectScoreValidator` проверяет тип и числовые границы | Логику проверки диапазонов можно адаптировать в новом service, не привязывая Evaluation к ProjectScore |
| Эксперт | `users.Expert` связан OneToOne с User и ManyToMany с PartnerProgram | Профиль и membership Program переиспользуются |
| Назначение | `ProjectExpertAssignment`: Program, Project, Expert | Не переиспользовать: target — Project; нет назначения на конкретную версию Submission |
| Распределение | `PartnerProgram.is_distributed_evaluation` включает фильтрацию назначенных Project | Новый контур всегда требует явного назначения на Submission; legacy-флаг не определяет новые права |
| Лимит | `PartnerProgram.max_project_rates` ограничивает число экспертов Project | Не применять автоматически к Submission без отдельного продуктового решения |
| Дедлайн | `PartnerProgram.datetime_evaluation_ends` | Кандидат на общий дедлайн, но его совместное использование legacy/React flow нужно подтвердить |
| Permissions | `IsExpert` проверяет роль и membership Program; `IsExpertPost` проверяет только `user_type` | Недостаточно: новый доступ обязан проверять активное назначение на Submission |
| API | `GET/POST /rate-project/<program_id>`, `POST /rate-project/rate/<project_id>` | Остается неизменным только для Angular/legacy Project flow |
| Serializer | Возвращает Project и плоские criteria/score; повторный POST делает upsert | Нельзя использовать как Evaluation response: нет lifecycle и изоляции персональных данных |
| Admin | Criteria, ProjectScore и bulk ProjectExpertAssignment | Паттерны фильтров и bulk-назначения полезны, но новые сущности требуют отдельного admin |
| Экспорт | `/programs/<id>/export-rates/` читает ProjectScore | Новый Result/export не подключать к legacy-выгрузке автоматически |

Аудит опирается на:

- `project_rates/models.py`, `serializers.py`, `views.py`, `services.py`,
  `validators.py`, `permissions` в `users/permissions.py`;
- `project_rates/admin.py`, `signals.py`, `urls.py`;
- `users.Expert`, `PartnerProgram.experts`,
  `PartnerProgram.datetime_evaluation_ends`, `max_project_rates` и
  `is_distributed_evaluation`;
- `partner_programs.Submission`, Submission serializers, views, permissions,
  admin и API tests;
- tests модулей `project_rates`, `users` и export tests `partner_programs`;
- `docs/application-project-submission-rfc.md`,
  `docs/case-championship-domain.md` и `docs/modules/project-rates.md`.

Текущие tests подтверждают upsert ProjectScore, проверку membership эксперта,
Program/Project/Criteria consistency, диапазоны, лимит экспертов,
распределенные назначения, запрет удаления назначения после оценки и legacy
Excel export. Эти правила полезны как reference, но не являются тестами
Evaluation по Submission.

## 2. Проблема legacy ProjectScore

`ProjectScore` нельзя расширить до новой Evaluation без смешения двух контуров:

- `Project` может измениться после оценки, а `Submission` фиксирует конкретную
  версию решения;
- одна строка ProjectScore представляет один критерий, поэтому у полной формы
  эксперта нет атомарного статуса `draft/submitted`;
- отдельного комментария нет: signal создает специальный строковый критерий
  «Комментарий»;
- нет `submitted_at`, блокировки после отправки и управляемого возврата к
  редактированию;
- назначение связано с `Project`, а не с `Submission.stage_key/version`;
- legacy API раскрывает Project-oriented response и не подходит для
  минимизированного экспертного serializer;
- изменение ProjectScore или старых endpoints создает риск для Angular,
  export и production flow.

Поэтому новый контур добавляется рядом с `project_rates`. Автоматический
backfill ProjectScore в Evaluation и обратная синхронизация не входят в MVP.

## 3. Целевая модель

### Выбор хранения критериев

Для MVP выбран **вариант B**:

- одна `Evaluation` хранит владельца, статус, комментарий, итог и lifecycle
  полной формы;
- отдельная `EvaluationScore` хранит значение каждого критерия.

Вариант A с JSON внутри Evaluation проще по количеству таблиц, но не дает
надежной ссылочной целостности, uniqueness по критерию, удобной проверки
полноты формы и безопасной аналитики. Изменение одного элемента JSON также
сложнее аудитировать.

Нормализованный вариант позволяет атомарно отправлять всю форму в service,
сохраняя DB uniqueness для каждого критерия.

### SubmissionExpertAssignment

Отдельная сущность назначения эксперта на конкретную Submission.

Предлагаемые поля:

- `id`;
- `submission`, FK на `partner_programs.Submission`;
- `expert`, FK на `users.Expert`;
- `status`;
- `assigned_by`, FK на User;
- `assigned_at`;
- `revoked_by`, nullable FK на User;
- `revoked_at`, nullable;
- `revoke_reason`, blank;
- `completed_at`, nullable;
- `created_at`, `updated_at`.

Назначения не удаляются через публичный API. Повторное назначение после
отзыва создает новый исторический episode. Текущее активное назначение
определяется статусом, а не последней строкой без проверки.

### Evaluation

Одна форма одного эксперта для одной Submission.

Предлагаемые поля:

- `id`;
- `submission`, FK на Submission;
- `expert`, FK на `users.Expert`;
- `status`;
- `comment`, blank;
- `total_score`, nullable Decimal;
- `submitted_at`, nullable;
- `created_at`, `updated_at`.

`total_score` не принимается как доверенное клиентское значение. Оно
вычисляется backend service только при наличии согласованной настройки
формулы Program. Пока формулы нет, поле остается `null`.

### EvaluationScore

Предлагаемые поля:

- `id`;
- `evaluation`, FK на Evaluation, related name `scores`;
- `criterion`, FK на `project_rates.Criteria` с `PROTECT`;
- `value`, Decimal;
- snapshot-поля `criterion_name`, `criterion_type`, `min_value`, `max_value`;
- `created_at`, `updated_at`.

Для первого MVP `Criteria` можно переиспользовать как Program-scoped каталог,
потому что он уже имеет admin, тип и числовые границы. При этом:

- допускаются только числовые `int/float` Criteria;
- legacy-критерий «Комментарий» не становится EvaluationScore: комментарий
  хранится в `Evaluation.comment`;
- принадлежность Criteria той же Program проверяет новый service;
- snapshot фиксирует смысл критерия на момент оценки;
- `ProjectScore` и `ProjectScoreValidator` не становятся частью target-модели.

Если продукту нужны weight, order, required, active и versioned schema, нужен
отдельный `EvaluationCriterion` в самостоятельном PR. Не следует молча
добавлять эти значения в legacy Criteria.

## 4. Сущности и связи

```text
PartnerProgram
 ├── experts ── users.Expert
 ├── criterias ── project_rates.Criteria (переходный каталог)
 └── applications
      └── submissions
           ├── SubmissionExpertAssignment ── Expert
           └── Evaluation ── Expert
                └── EvaluationScore ── Criteria
```

Инварианты:

- `Evaluation.submission.program` совпадает с Program каждого Criteria;
- эксперт Evaluation совпадает с экспертом активного назначения;
- эксперт должен состоять в `submission.program.experts`;
- Evaluation создается только для `submitted` или `final` Submission;
- участник, Team и Project не являются владельцами Evaluation;
- одна Submission может иметь несколько экспертов и по одной Evaluation
  каждого эксперта;
- Evaluation не изменяет Submission, Project или Application.

Cross-table и ManyToMany invariants проверяются транзакционным domain service.
Их нельзя надежно выразить обычным `CheckConstraint`.

## 5. Статусы и переходы

### Статусы назначения

| Статус | Назначение | Допустимый переход |
|---|---|---|
| `assigned` | Эксперт может читать работу и вести draft Evaluation | `completed` или `revoked` |
| `completed` | Эксперт отправил Evaluation | Терминальный в MVP |
| `revoked` | Менеджер снял эксперта до финальной оценки | Терминальный; новое назначение — новая строка |

Правила:

- назначение создается сразу как `assigned`;
- `assigned → completed` выполняется атомарно вместе с submit Evaluation;
- `assigned → revoked` разрешен менеджеру до submit Evaluation;
- `completed` нельзя отозвать: требуется отдельная процедура аннулирования
  финальной оценки, которой нет в MVP;
- draft Evaluation при revoke сохраняется, но становится недоступной эксперту;
  повторное назначение того же эксперта может продолжить этот draft.

### Статусы Evaluation

| Статус | Редактирование | Допустимый переход |
|---|---|---|
| `draft` | Назначенным экспертом | `submitted` |
| `submitted` | Запрещено | Терминальный в MVP |

MVP намеренно не добавляет `cancelled`, `revised` или `reopened` без готового
audit contract. Возврат submitted Evaluation к редактированию запрещен.

Будущее явное правило может добавить manager-only action `reopen` с
обязательной причиной. До перехода прежняя финальная форма и scores должны
копироваться в неизменяемую revision/audit запись. Нельзя просто перевести
submitted Evaluation обратно в draft и перезаписать исторический результат.

### Submission во время оценки

Новый статус `in_review` в Submission не нужен. Состояние оценки вычисляется
из назначения и Evaluation:

- `submitted` — версия зафиксирована и может быть назначена эксперту;
- `final` — зафиксированная версия также может оцениваться;
- `returned` — редактируется участником, новые/финальные Evaluation запрещены;
- `draft` и `cancelled` — не назначаются и не оцениваются.

Derived UI-состояния: `not_assigned`, `assigned`, `evaluation_draft`,
`evaluated`. Они не сохраняются как новые Submission statuses.

## 6. Права доступа

| Роль | Submission | Evaluation | Назначения |
|---|---|---|---|
| Участник/капитан | Свои работы по существующим правилам | Только опубликованный итог/комментарий по отдельной Program policy | Нет |
| Accepted TeamMember | Read-only своей Application/Submission | Только разрешенный опубликованный результат | Нет |
| Эксперт | Только активно назначенные или завершенные им Submission | Создает/редактирует только свой draft, читает свою submitted Evaluation | Нет |
| Менеджер Program | Submission, назначения и Evaluation только своей Program | Read-only всех форм; future reopen только отдельным action | Назначает и отзывает до submit |
| Staff/superuser | Административный доступ | Административный доступ с audit | Административный доступ |
| Посторонний эксперт | Нет | Нет | Нет |

Обязательные правила:

- membership `Expert.programs` сам по себе не дает доступ ко всем Submission;
- активное/завершенное назначение проверяется для каждого объекта;
- чужой или неназначенный Submission возвращается как 404, чтобы не
  подтверждать его существование;
- участник никогда не видит draft Evaluation или внутренние manager notes;
- submitted комментарий показывается участнику только после явного правила
  публикации Program; до появления policy participant Evaluation endpoint не
  добавляется;
- manager не подменяет эксперта и не редактирует его scores напрямую;
- staff-действия должны логировать actor и причину.

Новые permissions должны жить рядом с Submission/Evaluation domain helpers.
Legacy `IsExpert` и особенно `IsExpertPost` недостаточны: последний проверяет
только `user_type`, но не назначение.

## 7. API-контракт

Все endpoints требуют authentication. JSON использует обычный DRF contract.
Ошибки:

- `401` — пользователь не авторизован;
- `403` — роль не позволяет выполнить действие в известном Program context;
- `404` — Submission/Evaluation/assignment отсутствует или скрыта object-level
  permission;
- `400` — payload, Criteria или диапазон невалидны;
- `409` — конфликт статуса, повторное активное назначение или закрытая форма;
- `429` — scoped throttle.

### Expert cabinet

#### `GET /expert/submissions/`

Права: Expert видит только свои `assigned` и `completed` назначения; staff
может использовать административный режим отдельно.

Query: опционально `program_id`, `submission_status`, `evaluation_status`,
pagination.

Response item:

```json
{
  "id": 42,
  "program": {"id": 7, "name": "Case Championship"},
  "title": "Решение",
  "status": "submitted",
  "stage_key": "main",
  "version": 2,
  "submitted_at": "2026-08-31T18:00:00Z",
  "assignment": {
    "id": 15,
    "status": "assigned",
    "assigned_at": "2026-09-01T09:00:00Z"
  },
  "my_evaluation": {
    "id": 9,
    "status": "draft",
    "updated_at": "2026-09-02T10:00:00Z"
  }
}
```

Endpoint безопасен для повторов. Дополнительный mutation throttle не нужен.

#### `GET /expert/submissions/<submission_id>/`

Права: назначенный эксперт или staff. Для неназначенного эксперта — 404.

Response содержит только solution-поля Submission, разрешенную часть
`form_data`, criteria snapshot для формы, assignment и собственную Evaluation.
Application form, User, TeamMember, email, phone и `submitted_by` не
возвращаются.

Endpoint безопасен для повторов. Дополнительный mutation throttle не нужен.

### Evaluation эксперта

#### `GET /submissions/<submission_id>/evaluations/my/`

Права: назначенный эксперт. Слово `my` означает Evaluation текущего эксперта,
а не Evaluation участника Submission.

Response: `200` с собственной Evaluation и scores; `404`, если Evaluation еще
не создана или Submission не назначена. GET ничего не создает.

#### `POST /submissions/<submission_id>/evaluations/`

Права: эксперт с текущим `assigned` assignment; Submission имеет статус
`submitted/final`.

Request:

```json
{
  "comment": "Сильная аргументация",
  "scores": [
    {"criterion_id": 3, "value": "8.5"},
    {"criterion_id": 4, "value": "7"}
  ]
}
```

Создает draft и атомарно валидирует Criteria, Program и диапазоны. Пустой
draft допустим, если UI создает его перед первым autosave.

Идемпотентность: uniqueness `submission + expert` и `get_or_create` под
transaction. Первый запрос возвращает `201`; повтор при существующем draft
возвращает `200` без неявного изменения данных. Для изменения используется
PATCH. При существующей submitted Evaluation возвращается `409`.

Рекомендуемый scope: `evaluation_create`, default `10/min`.

#### `GET/PATCH /evaluations/<evaluation_id>/`

GET: владелец-эксперт, manager соответствующей Program или staff. Для
участника endpoint закрыт.

PATCH: только владелец-эксперт, активное назначение и статус `draft`.

Request может содержать `comment` и `scores`. Если передан `scores`, service
атомарно заменяет набор scores формы, а не оставляет неоднозначный частичный
набор. `submission`, `expert`, `status`, `total_score` и timestamps read-only.

Повторная установка тех же значений идемпотентна. Ошибка диапазона — 400;
чужой объект — 404; revoked assignment или submitted Evaluation — 409.

Для PATCH/autosave нужен отдельный разумный rate, например
`evaluation_update=120/min`; POST-only throttle его не покрывает.

#### `POST /evaluations/<evaluation_id>/submit/`

Права: владелец-эксперт с активным назначением.

Request: пустой объект.

Service под transaction и row locks:

1. повторно проверяет assignment и статус Submission;
2. проверяет наличие всех обязательных Criteria;
3. валидирует scores;
4. вычисляет `total_score`, только если Program имеет формулу;
5. переводит Evaluation в `submitted`;
6. фиксирует `submitted_at`;
7. переводит assignment в `completed`.

Повторный submit уже submitted Evaluation возвращает тот же объект с `200` и
не изменяет `submitted_at`. Другие конфликты состояния — 409.

Рекомендуемый scope: `evaluation_submit`, default `20/min`.

### Назначение экспертов менеджером

#### `GET /programs/<program_id>/submission-assignments/`

Права: manager Program или staff.

Query: `submission_id`, `expert_id`, `status`. Response содержит историю
назначений и краткий статус Evaluation, но не participant form data.

#### `POST /programs/<program_id>/submission-assignments/`

Права: manager Program или staff.

Request:

```json
{
  "submission_id": 42,
  "expert_id": 11
}
```

Проверяет Program, статус Submission, Expert membership и отсутствие другого
активного/завершенного назначения этой пары.

Первое назначение — `201`. Повтор того же запроса при уже `assigned` возвращает
существующую строку с `200`. После `revoked` создается новый episode.
`completed` или конфликт Program возвращает 409/400 соответственно.

Рекомендуемый scope: `submission_assignment_create`, default `60/min`.

#### `POST /submission-assignments/<assignment_id>/revoke/`

Права: manager соответствующей Program или staff.

Request:

```json
{
  "reason": "Перераспределение нагрузки"
}
```

Допустим только переход `assigned → revoked`, пока Evaluation не submitted.
Повторный revoke возвращает ту же строку с `200` и не меняет `revoked_at`.
Completed assignment возвращает 409.

Delete endpoint не используется, чтобы сохранять историю.

### Не входящий в MVP reopen

Если продукт подтвердит исправление финальной оценки, отдельный manager action
может иметь вид `POST /evaluations/<id>/reopen/`. Он требует reason и
неизменяемого snapshot предыдущей submitted revision. До реализации revision
model endpoint добавлять нельзя.

## 8. DB constraints

Обязательные ограничения:

1. Partial `UniqueConstraint(submission, expert)` для assignment в статусах
   `assigned/completed`. Он исключает два активных назначения и новое
   назначение после завершенной оценки; несколько `revoked` строк сохраняют
   историю.
2. `UniqueConstraint(submission, expert)` для Evaluation.
3. `UniqueConstraint(evaluation, criterion)` для EvaluationScore.
4. Общий `value >= 0` не добавляется без продуктового правила: существующий
   Criteria может допускать другой диапазон. Индивидуальные min/max являются
   cross-row правилом и проверяются service/model validation; для Criteria
   типа `int` дополнительно запрещается дробное значение.
5. `submitted_at IS NOT NULL` для submitted Evaluation и `IS NULL` для draft,
   если синтаксис текущей версии Django/PostgreSQL позволяет выразить это без
   неоднозначности.
6. Assignment timestamps согласуются со статусом: revoked требует
   `revoked_at`, completed требует `completed_at`.

Транзакционный service дополнительно проверяет:

- `submission.program` соответствует Program manager endpoint;
- Expert состоит в `submission.program.experts`;
- Criteria относится к `submission.program`;
- Submission имеет `submitted/final`;
- значения находятся в диапазонах Criteria;
- набор обязательных Criteria полон;
- submit и assignment transitions выполняются с `select_for_update`;
- IntegrityError преобразуется в контролируемый 409, а не 500.

Связь Submission с другой Program и Expert membership нельзя проверить
простым DB constraint: это FK/M2M cross-table invariants.

Поведение при снятии эксперта:

- assignment остается в истории как `revoked`;
- draft Evaluation и scores не удаляются, но блокируются для эксперта;
- submitted Evaluation запрещает revoke;
- hard delete Evaluation из публичного API отсутствует.

История финальной оценки сохраняется неизменностью submitted Evaluation.
Будущий reopen требует отдельной revision/audit модели; перезапись submitted
scores недопустима.

## 9. Безопасность персональных данных

Экспертный serializer строится отдельно от participant/manager serializers.
Он не должен возвращать:

- `Application.user`, `created_by` и registration `form_data`;
- Team, TeamMember, приглашения и contact data;
- email, phone, город, образование и другие поля профиля;
- внутренние manager notes;
- Evaluation других экспертов.

Эксперту достаточно:

- идентификатора/анонимного кода Submission;
- Program, stage и version;
- title, description, links;
- только разрешенных полей solution `form_data`;
- criteria;
- собственного assignment и собственной Evaluation.

Если `Submission.form_data` допускает произвольные ключи, нельзя отдавать его
эксперту целиком без schema allowlist. До появления field-level policy
безопаснее возвращать только явно известные solution-поля.

Логи не должны содержать полный payload Evaluation или персональные данные.
Manager/staff actions записывают actor, object id, transition и reason.

## 10. Совместимость

RFC не меняет:

- `Project`, `ProjectScore`, `ProjectExpertAssignment` и Criteria API;
- `PartnerProgramProject`, `PartnerProgramUserProfile`;
- Application, Team, TeamInvite и Submission model/API;
- `/rate-project/` и `/programs/<id>/export-rates/`;
- старый Angular flow;
- production и React-dev;
- settings, Docker, nginx и GitHub Actions.

Новые таблицы и endpoints должны жить рядом с legacy-контуром. Нельзя:

- автоматически создавать ProjectScore из Evaluation;
- включать Evaluation в legacy export без отдельного contract;
- считать `max_project_rates` лимитом новых назначений;
- давать Expert доступ через общий Submission detail только на основании роли;
- менять Submission status при сохранении draft Evaluation;
- реализовывать Result в Evaluation PR.

## 11. План следующих PR

1. **Evaluation models.** Добавить `SubmissionExpertAssignment`, `Evaluation`,
   `EvaluationScore`, migrations, admin, constraints и model tests. API не
   добавлять.
2. **Assignment service/API.** Транзакционные manager permissions,
   list/create/revoke, history и tests.
3. **Expert Submission read API.** Изолированный queryset, PII-safe serializer,
   criteria contract и object-level permission tests.
4. **Evaluation mutation API.** Draft create/update/submit, idempotency,
   locking, ranges, completeness и throttling.
5. **Manager evaluation read API.** Просмотр форм/статусов своей Program без
   редактирования экспертных scores.
6. **React expert cabinet.** Список назначений, detail, autosave draft и
   финальная отправка.
7. **Publication and Result RFC.** Настройка видимости участнику, формула
   агрегации, ranking и ручное решение менеджера. Только после этого —
   participant result UI/export.

Каждый coding PR должен сохранять legacy tests и добавлять собственные
permission, transition, concurrency и PII regression tests.

## 12. Открытые продуктовые вопросы

1. Считать ли `datetime_evaluation_ends` общим дедлайном ProjectScore и
   Submission Evaluation или нужен отдельный deadline?
2. Остается ли legacy Criteria временным каталогом или до первого coding PR
   нужны `EvaluationCriterion`, order, weight, required и schema version?
3. Все ли criteria обязательны при submit и допустимы ли текстовые/boolean
   ответы кроме общего комментария?
4. Как ограничивается число экспертов одной Submission? Нельзя автоматически
   переиспользовать `max_project_rates`.
5. Должен ли эксперт видеть автора/команду или оценивание всегда анонимное?
6. Какие `Submission.form_data` поля безопасно показывать эксперту?
7. Когда участник видит submitted score и comment: сразу, после дедлайна,
   после решения менеджера или только после публикации Result?
8. Нужен ли manager-only reopen? Если да, какая revision/audit модель хранит
   предыдущую финальную форму?
9. Какая Submission version оценивается при нескольких stage/version и можно
   ли назначать одновременно несколько версий одной Application?
10. Какая формула вычисляет `total_score`: сумма, среднее, weights или ручное
    значение? До настройки Program поле остается `null`.
11. Может ли manager одновременно быть назначенным экспертом? Если да, права
    evaluator и manager должны проверяться как разные действия.
12. Нужно ли уведомление при назначении, отзыве и submit Evaluation? Delivery
    не входит в первые model/API PR.

## Итоговый результат в будущем

`Result` в этом RFC не реализуется. После появления финальных Evaluation
отдельный слой может рассчитывать:

- средний балл;
- сумму;
- взвешенный балл;
- ручное решение менеджера;
- комбинацию автоматического результата и ручной модерации.

Формулу нельзя зашивать в Evaluation service без настройки Program.
Evaluation сохраняет исходные финальные оценки; будущий Result хранит
агрегат, правило расчета, момент фиксации и публикации.
