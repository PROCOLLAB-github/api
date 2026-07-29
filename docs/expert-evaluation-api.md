# Expert Evaluation API

## Roadmap

- DEV-050 — Expert Submission API
- DEV-051 — Evaluation mutation API
- DEV-052 — Manager evaluation read API
- DEV-073 — изменение submitted Evaluation с неизменяемой историей

Roadmap-IDs: DEV-050, DEV-051, DEV-052, DEV-073

## Назначение

Контур позволяет назначенному эксперту читать зафиксированную версию
`Submission`, вести черновик оценки и финально отправлять его. Менеджер
программы получает отдельный read-only доступ к оценкам экспертов.

Эксперт оценивает `Submission`, а не изменяемый legacy `Project`. Права на
объект определяются `SubmissionExpertAssignment`, а не одной ролью Expert или
membership в программе.

## Сущности

- `SubmissionExpertAssignment` связывает конкретную Submission и Expert.
- `Evaluation` хранит форму оценки, комментарий и lifecycle.
- `EvaluationScore` хранит одно числовое значение и snapshot критерия.
- `EvaluationAmendment` хранит неизменяемые снимки до и после изменения
  отправленной оценки.
- `project_rates.Criteria` временно используется как каталог критериев
  программы.

`ProjectScore`, `ProjectExpertAssignment` и `/rate-project/` в новый контур не
включены и не синхронизируются с Evaluation.

## Статусы и переходы

Assignment:

- `assigned` — эксперт может создавать и изменять draft;
- `completed` — Evaluation отправлена, эксперт сохраняет read-only доступ;
- `revoked` — доступ эксперта закрыт, но draft и scores не удаляются.

Evaluation:

- `draft` — доступно атомарное обновление `comment` и полного набора `scores`;
- `submitted` — отправленное состояние; обычный PATCH запрещен, изменение
  возможно только через DEV-073 amend с audit-записью.

Финальный submit в одной транзакции переводит Evaluation в `submitted`, а
assignment в `completed`. Amend не возвращает Evaluation в draft, не меняет
`submitted_at` и сохраняет историю. Reopen отсутствует.

## Права доступа

- Expert list/detail доступны только эксперту с текущим membership программы
  и assignment `assigned` или `completed`.
- Создание и изменение draft требуют assignment `assigned`.
- Amend submitted Evaluation доступен только владельцу при assignment
  `assigned` или `completed` и текущем membership программы.
- Историю amend читают владелец, manager программы и staff/superuser.
- Staff может открыть PII-safe expert detail в административном режиме.
- Владелец-эксперт, manager программы и staff могут читать Evaluation detail.
- Manager list/detail ограничены конкретной программой.
- Неназначенному или чужому эксперту объект возвращается как `404`.
- Manager API не имеет PATCH, DELETE, submit или reopen.

Одна роль Expert, membership в программе или доступ к legacy ProjectScore не
создают object-level право.

## Expert API

### GET /expert/submissions/

Возвращает пагинированный список назначенных решений. Фильтры:

- `program_id`;
- `submission_status`;
- `evaluation_status`: `draft`, `submitted`, `none`;
- стандартные `limit` и `offset`.

Элемент содержит PII-safe Submission summary, Program, assignment и только
Evaluation текущего эксперта.

### GET /expert/submissions/\<submission_id\>/

Возвращает `title`, `description`, отдельное поле `links`, status, stage,
version, Program, assignment, собственную Evaluation и числовые Criteria.

`Submission.form_data` не возвращается. В текущем домене нет надёжного
solution-only allowlist, поэтому частичная выдача JSON была бы небезопасной.
Также не возвращаются Application, participant, Team, registration data,
email, phone и Evaluation других экспертов.

### GET /submissions/\<submission_id\>/evaluations/my/

Возвращает существующую собственную Evaluation и scores. GET ничего не
создаёт. Отсутствующий draft или assignment возвращает `404`.

### POST /submissions/\<submission_id\>/evaluations/

Создаёт draft. `comment` и `scores` необязательны. Первый запрос возвращает
`201`; повторный POST возвращает существующий draft с `200` и не изменяет его.
Для submitted Evaluation возвращается `409`.

### GET /evaluations/\<evaluation_id\>/

Read-only detail для владельца-эксперта, manager соответствующей программы и
staff.

### PATCH /evaluations/\<evaluation_id\>/

Autosave владельца draft. Можно передать `comment`, `scores` или оба поля. Если
передан `scores`, старый набор заменяется целиком внутри транзакции. Пустой
массив удаляет все scores. Системные и lifecycle-поля read-only.

### POST /evaluations/\<evaluation_id\>/submit/

Проверяет полноту формы и атомарно завершает Evaluation и assignment.
Повторный submit идемпотентен: возвращает `200` и сохраняет первоначальный
`submitted_at`.

### PATCH /evaluations/\<evaluation_id\>/amend/

Изменяет `comment` и/или полный набор `scores` уже отправленной Evaluation.
Endpoint доступен только эксперту-владельцу. Evaluation остается `submitted`,
исходный `submitted_at` сохраняется, `amended_at` обновляется, а `total_score`
сбрасывается в `null` до появления формулы пересчета.

Если передан `scores`, payload обязан содержать все текущие числовые Criteria
программы. Валидация и замена scores, обновление Evaluation и создание
`EvaluationAmendment` выполняются в одной транзакции. Полностью совпадающий
запрос возвращает `200`, но не обновляет `amended_at` и не создает историю.

### GET /evaluations/\<evaluation_id\>/amendments/

Возвращает упорядоченную неизменяемую историю со снимками comment, scores и
total_score до и после каждой правки. Доступ имеют эксперт-владелец, manager
программы и staff/superuser. Для остальных существование Evaluation скрывается
ответом `404`.

## Manager API

### GET /programs/\<program_id\>/submission-assignments/

Существующий контракт дополнен nullable-полем `evaluation` с полями `id`,
`status`, `updated_at`, `submitted_at`, `amended_at`, `total_score`. Старое поле
`evaluation_status` сохранено.

### GET /programs/\<program_id\>/evaluations/

Пагинированный read-only список. Фильтры:

- `submission_id`;
- `expert_id`;
- `evaluation_status`;
- `assignment_status`;
- `stage_key`;
- `limit`, `offset`.

Ответ содержит безопасные Submission/Expert/Assignment summaries, scores,
comment, total_score, `submitted_at`, `amended_at` и остальные timestamps.

### GET /programs/\<program_id\>/evaluations/\<evaluation_id\>/

Read-only detail в пределах программы manager. Mutation-методы отсутствуют.

## Валидация критериев

- Используются только Criteria той же Program типов `int` и `float`.
- Criterion ID не может повторяться в одном payload.
- Для `int` запрещена дробная часть.
- Значения проверяются по текущим `min_value` и `max_value` без преобразования
  Decimal через float.
- PATCH сначала валидирует весь новый набор и только затем удаляет старый.
- Submit требует все текущие числовые Criteria программы и повторно проверяет
  типы и диапазоны.
- Amend с `scores` также требует полный набор текущих числовых Criteria до
  начала любых изменений.
- Нечисловые Criteria не включаются в форму; свободный текст хранится в
  `Evaluation.comment`.

## Идемпотентность

- Повторный create существующего draft возвращает его без изменения.
- Повторный PATCH с теми же данными не создаёт дублей.
- Повторный submit submitted Evaluation не меняет `submitted_at`.
- Повторный amend с теми же comment и scores не создает новую историю и не
  меняет `amended_at`.
- Уникальность `submission + expert` и `evaluation + criterion` дополнительно
  защищена существующими constraints.

## Транзакции и блокировки

- Create блокирует assignment и обрабатывает race через вложенный savepoint
  вокруг INSERT Evaluation.
- PATCH блокирует assignment и Evaluation; набор scores заменяется атомарно.
- Submit блокирует assignment и Evaluation в стабильном порядке, валидирует
  полную форму и записывает одинаковый timestamp в Evaluation и assignment.
- Amend блокирует assignment и Evaluation в том же порядке, затем атомарно заменяет scores,
  обновляет Evaluation и записывает снимок `EvaluationAmendment`.
- Два конкурентных submit не создают противоречивое терминальное состояние.

## Защита персональных данных

Expert serializers построены отдельно от participant serializers. В ответах
нет Application user/creator, submitted_by, Team, TeamMember, registration
form_data, email или phone. `Submission.form_data` полностью исключён до
появления явной схемы разрешённых solution-полей.

Manager responses содержат только минимальные имя/фамилию назначенного
эксперта и не содержат данные участника. Полные request payload не логируются
новым кодом.

## Throttling

- `evaluation_create`: `10/min`;
- `evaluation_update`: `120/min`;
- `evaluation_submit`: `20/min`;
- `evaluation_amend`: `30/min`.

Scopes применяются только к соответствующим mutation-методам и не включают
глобальный DRF throttle.

## Ошибки API

- `200` — успешное чтение, autosave, повторный create или submit;
- `201` — первый draft create;
- `400` — payload, Criteria, тип, диапазон или неполная форма;
- `401` — отсутствует авторизация;
- `403` — нет доступа к list/manager endpoint;
- `404` — объект отсутствует или скрыт object-level политикой;
- `409` — lifecycle conflict Evaluation, assignment или Submission;
- `429` — превышен scoped throttle.

## Проверка

Основной regression-модуль:

`partner_programs.tests.test_expert_evaluation_api`

Он покрывает expert list/detail, PII regression, draft create, полную замену
scores, rollback, submit lifecycle, amend submitted Evaluation, audit history,
concurrent submit, manager read-only API, filters, pagination и throttling.

Также сохраняются model tests и Assignment API regression.

## Известные ограничения

- `total_score` остаётся `null`, пока у Program нет формулы.
- Criteria не имеют отдельного Evaluation order/weight/required policy:
  обязательны все текущие числовые Criteria.
- Staff expert detail выбирает последнее активное или завершённое назначение
  Submission для административного просмотра.
- Deadline `datetime_evaluation_ends` пока не блокирует новый контур.

## Что не входит в контур

- frontend и экспертный кабинет;
- Result, ranking и публикация участнику;
- экспорт Evaluation;
- уведомления;
- reopen и revision history;
- веса и формула total_score;
- изменение legacy Criteria;
- синхронизация с ProjectScore;
- изменение `/rate-project/`, Angular flow или старой выгрузки.
