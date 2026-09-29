# Конкурсная legacy-команда (PR C)

Основание — утверждённое ТЗ hardening и уточнения пользователя от 29.09.2026.
База: PR B `3a513846c81dd36e5f3393957ec3450c9fcfb2f7`.

## Current / target, роли и правила

До: legacy submitted не запрещает team mutation, program context выбирался первым
link, нет ограничений размера или конкурентной exclusivity. Target: общая policy
для Invite, Collaborator, switch/leave/remove, vacancy accept, apply/bind/clone,
admin/model validation и link-scoped submission. Управление командой по-прежнему
только у лидера; существующий staff override vacancy service сохраняется.

- Exclusivity: все draft/submitted Project links конкурсной программы до
  `datetime_finished`. Завершённые программы сохраняют историю без exclusivity.
- Freeze: любой submitted competitive link запрещает изменение общего состава
  Project; explicit context другой программы не может обойти этот freeze.
- Draft разрешён одному лидеру. Минимум проверяется только на submission.
- Leader входит в accepted unique user IDs один раз. Pending unique recipients
  резервируют max capacity, но не учитываются в submission minimum.
- Каждая NULL-граница отключает только своё ограничение.
- Decline/revoke pending разрешены после submission и освобождают reservation.

## Схема / совместимость до создания migration

DEV PartnerProgram не содержит min/max. PROD PartnerProgram `team_min_size` и
`team_max_size` зависят от nextgen `participation_format`: запрещены для individual,
обязательны обе для team, каждое >= 2. Это несовместимо с nullable legacy semantics.
Новые настройки: `legacy_team_min_size`, `legacy_team_max_size`, nullable без data
defaults/backfill. Значения nextgen не копируются. Ограничивается только корректность
конфигурации: положительные значения и min <= max, если заданы обе границы.

Invite получает nullable `program_link → PartnerProgramProject` с RESTRICT:
исторический контекст нельзя потерять из-за удаления link; удаление всего Project
по cascade может удалить и Invite, и link. Новый Invite программного Project хранит
конкретный link. Backfill только для ровно одного link; ноль / несколько остаются NULL.
Для ambiguous legacy Invite accept/edit требуют explicit `program_link_id` либо 409
`program_context_required`; decline/revoke не добавляют участников и доступны для
безопасного завершения pending. Migration не выбирает программу по минимальному PK.

## Транзакции и resolver

Единый порядок существующего Project: `Project → PartnerProgram (sorted IDs) →
PartnerProgramProject (sorted IDs) → Invite / Vacancy → PUP / Collaborator`.
Project lock сериализует смену links и roster. Program locks сериализуют writers
разных проектов одной программы; актуальный PUP блокируется до записи membership.
Создание нового Project при apply начинается с целевой Program: новый Project ещё
не доступен другим writers. Все проверки выполняются повторно внутри transaction.

Context: ноль links → обычный проект; один → единственная связь; несколько →
explicit ID из этого Project либо 409. Submission сохраняет link ID в URL.
Поскольку Collaborator общий для всех links Project, при добавлении проверяются
membership/exclusivity/capacity всех затронутых программ, а не только выбранной.

## Acceptance criteria / план проверки

| AC | Предусловие / действие / результат |
| --- | --- |
| C1 | Submitted: create/edit/accept/add/vacancy/remove/leave/switch → team_frozen |
| C2 | Submitted: pending decline/revoke успешны |
| C3 | Leader/collaborator в A не может войти в B той же активной программы |
| C4 | Разные программы и завершённые программы не дают ложной exclusivity |
| C5 | Два concurrent accept в разные команды одной программы → один успех |
| C6 | Solo draft допустим; configured minimum проверяется на submit |
| C7 | Exact min/max допустимы; max+1 с pending reservation запрещён |
| C8 | Ноль / один / два links, explicit правильный / чужой ID проверены |
| C9 | Membership каждого accepted участника повторно проверяется на submit |
| C10 | Submit+accept / submit+remove не оставляют изменяемую submitted-команду |
| C11 | Apply/create/bind/clone/vacancy/admin/model не обходят policy |
| C12 | Recommendations содержат только actionable candidates |
| C13 | Team-size export считает уникальные accepted IDs |
| C14 | Migration backfill не угадывает контекст и не изменяет roster |
| C15 | Обычные проекты сохраняют прежние успешные flows |

UI — только отдельный PR D; без redesign и нового recommendations UI. React,
production data, merge, deploy и unrelated analytics не входят в scope.
Data audit и rollout diagnostics не выбирают победителя существующих конфликтов.

## API contract

`program_link_id` — optional positive integer: body create/edit/accept Invite,
switch/direct-add; query remove/leave/recommended_users; body bind/update Project
и vacancy accept. Запрос с ID другой связи → 422 `invalid_program_context`.
Сохранённый Invite context нельзя переназначить. Decline/revoke context не требуют.
Link-scoped submission URL не менялся.

Project list/detail и компактные `/auth/users/projects[/leader]/` возвращают
`team_policy`: `is_frozen`, `program_link_id` только для единственной связи,
`requires_program_context`, `program_links[{id,program_id,is_submitted,is_competitive}]`.
Legacy singular `partner_program` остаётся read compatibility projection;
его first-link presentation не используется для новых business mutations.

Новые 409: `team_frozen`, `already_in_program_team`, `team_min_size`,
`team_max_size`, `program_context_required`, `program_context_in_use`,
`submission_closed`; existing B codes сохраняются. Permission — 403;
неверный context — 422; malformed input и existing submission/case validation — 400.
Admin показывает Django form validation / controlled conflict вместо 500.

## DB guarantees и пределы

DB: existing unique Collaborator(user,project), unique PUP(user,program),
pending Invite constraint PR B; новые FK Invite.program_link и checks корректности
min/max конфигурации. Нет отдельной таблицы с unique(user,program,active_team):
exclusivity по нескольким таблицам и времени гарантируют Program locks и повторная
проверка поддерживаемых writers. Прямой SQL, QuerySet.update/bulk_create/cascade
удаление целых родительских сущностей не являются защищёнными roster-service командами.
Новые maintenance/import writers должны соблюдать service protocol. Для независимой
от writers DB-гарантии потребуется отдельная materialized membership сущность и
согласованная миграция; она не добавляется молча в этот PR.

## Verification / review

115 targeted PostgreSQL tests PASS: competitive policy (29 cases), все Invite tests,
forward/backward migrations, admin field mutations и case locking. Среди новых
проверок — real HTTP races: accept A/B, invite capacity, submit/accept, submit/remove;
clone/bind rollback, model/API required fields, independent NULL bounds, DB bound
check, membership removal, explicit foreign context и any-submitted-link freeze.

Black/Flake8 изменённых/new Python файлов, Django check, migration consistency и
diff check PASS. Полный suite и GitHub PostgreSQL CI фиксируются в PR description.
UI/browser, live DEV/PROD mutations и deploy здесь не проверялись/не выполнялись.

Старые tests чтения сохраняют намеренно конфликтные historical fixtures через
bulk/queryset insert/update. Это не обход policy в production code: новые mutation
tests вызывают реальные API/service/model save и проверяют rejection/rollback.

## Rollout

1. A → dev; затем B → dev после смены base B; затем C → dev после смены base C.
2. До B/C на целевой БД прочитать `legacy-team-data-audit.sql`. Здесь live production
   audit не выполнялся. При duplicates migration B остановится, данные сохранятся.
3. C schema/backfill не удаляет конфликтные команды, не задаёт product min/max,
   ambiguous Invite оставляет NULL. Existing conflicts требуют отдельного решения
   владельца данных; до решения новые conflict-sensitive mutations возвращают 409.
4. После применения schema и backend отдельно внедрить Angular PR D (#392).
5. PROD имеет другой migration graph и nextgen lifecycle. Прямой cherry-pick
   migrations без согласования графа не является production release plan.

Review AC C1–C15: source и targeted assertions проверены; full-suite evidence
добавляется в описание PR после окончания проверки. Merge/deploy выполняет владелец.
