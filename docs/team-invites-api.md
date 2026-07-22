# Team Invites API

## Назначение

`TeamInvite` оформляет согласие существующего пользователя платформы войти в
команду конкретной `Application`. Приглашение не является членством и само по
себе не дает доступа к Application, Team или Submission. Только атомарный
`accept` создает либо восстанавливает `TeamMember` со статусом `accepted`.

Новый flow не использует `invites.Invite`: legacy-модель по-прежнему относится
только к `Project` и не менялась.

## Модель

`TeamInvite` хранит:

- `team`, `user` и `invited_by`;
- статус `pending`, `accepted`, `declined` или `revoked`;
- `resolved_at`, `created_at`, `updated_at`.

Условный `UniqueConstraint(team, user)` действует только для `pending`.
Завершенные строки остаются историей, после них пользователя можно пригласить
повторно. Индексы поддерживают список приглашений команды и пользователя.
Создание `TeamInvite` намеренно не создает предварительный `TeamMember`.

Миграция: `0022_teaminvite_teaminvite_uniq_pending_invite_team_user`.

## Endpoints

| Method | Endpoint | Доступ | Назначение |
|---|---|---|---|
| GET | `/applications/<application_id>/team/invite-candidates/?q=...` | captain, staff | Найти потенциальных кандидатов |
| GET | `/applications/<application_id>/team/invites/` | captain, staff | История приглашений Team |
| POST | `/applications/<application_id>/team/invites/` | captain, staff | Создать pending по `{"user_id": id}` |
| GET | `/team-invites/my/` | invitee | Собственные приглашения, pending первыми |
| POST | `/team-invites/<invite_id>/accept/` | invitee | Принять приглашение |
| POST | `/team-invites/<invite_id>/decline/` | invitee | Отклонить приглашение |
| POST | `/team-invites/<invite_id>/revoke/` | captain, staff | Отозвать приглашение |

Manager и accepted member видят Team read-only, но не список приглашений и не
могут управлять им. Вложенные профили содержат только `id`, `display_name` и
`avatar`; email и закрытые поля не выдаются.

Скрытый объект возвращает 404, известный объект без права на действие — 403,
нарушение статуса или domain invariant — 400.

## Создание

Создание разрешено только для командной draft-Application до
`datetime_application_ends`. Target должен:

- существовать и не быть капитаном либо accepted member этой Team;
- иметь `PartnerProgramUserProfile` в Program;
- не владеть другой активной Application этой Program;
- не быть accepted member другой активной Team этой Program.

Accepted-состав вместе с pending-приглашениями не должен превышать
`team_max_size`. Повторный запрос для уже существующего pending идемпотентно
возвращает его, не создавая новую строку.

## Поиск кандидатов

Поиск scoped к конкретной Team и не является глобальным каталогом пользователей.
Параметр `q` обязателен, очищается от пробелов и должен содержать от 3 до 100
символов. Поиск выполняется по имени, фамилии, обоим порядкам полного имени и
email prefix без учета обычных вариантов регистра. Email используется только
в ORM-фильтре и никогда не включается в response.

Selector возвращает не более 20 активных пользователей со стабильной
сортировкой. Каждый кандидат должен иметь Registration этой Program и не иметь:

- accepted membership или капитанства в текущей Team;
- pending TeamInvite в текущую Team;
- другой активной собственной Application в Program;
- accepted membership другой активной Team в Program.

Исторические declined/revoked invites, removed/left memberships и терминальные
Application не исключают кандидата. ORM использует `Exists`-подзапросы без
загрузки регистраций в Python, N+1 и размножающих строки join-ов.

Search не создает TeamInvite, TeamMember и не резервирует место. Перед поиском
проверяются draft, application deadline и свободное место с учетом accepted +
pending. После выбора `POST .../team/invites/` заново выполняет все проверки
под блокировкой Program, поэтому устаревший результат поиска нельзя использовать
для обхода domain invariants.

## Accept, decline и revoke

Все переходы блокируют строки в порядке Program → Application → Team →
TeamInvite. `accept` повторно проверяет Registration, конфликт активного
участия, вместимость, draft и deadline, затем:

1. создает или восстанавливает единственный `TeamMember(team, user)`;
2. устанавливает роль `member` и статус `accepted`;
3. сохраняет прежний `joined_at`, если пользователь уже состоял в Team;
4. переводит приглашение в `accepted` и заполняет `resolved_at`;
5. отзывает другие pending-приглашения пользователя в этой Program.

`accept` уже принятого, `decline` уже отклоненного и `revoke` уже отозванного
приглашения идемпотентны. Другие терминальные переходы возвращают 400. После
submit Application новые create/accept/decline/revoke запрещены.

Pending-приглашение блокирует смену team → individual, но не считается членом
команды при submit. Если accepted-состав соответствует policy Program, наличие
pending не мешает отправить Application.

## Domain errors

- `team_invite_permission_denied`;
- `team_invite_not_pending`;
- `team_invite_target_invalid`;
- `team_invite_registration_missing`;
- `team_invite_duplicate`;
- `team_invite_capacity_reached`;
- `team_invite_active_application_conflict`;
- `team_invite_not_owned`;
- общие `application_not_editable` и `application_deadline_passed`.

Mutation endpoints имеют независимые локальные scopes
`team_invite_create/accept/decline/revoke` с rate `20/min`. Scoped GET-поиск
использует отдельный `team_invite_candidate_search` с тем же rate. Остальные
GET endpoints этим throttle не ограничиваются; глобальные DRF settings не
менялись.

## Ограничения MVP

Приглашение работает только для существующего `user_id`. В MVP отсутствуют:

- приглашение по email, token или ссылке;
- expiry;
- email и in-app notifications;
- глобальный каталог и поиск пользователей вне контекста Team;
- organizer/manager mutation;
- frontend flow.

`Team.captain`, `Application.user/created_by/project`, Project и
`projects.Collaborator` при принятии приглашения не меняются.
