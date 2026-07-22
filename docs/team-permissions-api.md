# Team Permissions and API

## Назначение

Публичный Team API дает безопасный read-доступ к командной заявке и базовые
операции управления составом. `Team` относится к `Application`, а не к
`Project`; `projects.Collaborator` и legacy `invites.Invite` не участвуют в
этом flow.

Новых участников нельзя добавить напрямую в TeamMember. Согласие пользователя
оформляется отдельной сущностью `TeamInvite`; ее endpoints описаны в
`docs/team-invites-api.md`. Этот API читает состав, меняет название, фиксирует
выход/удаление и передает капитанство.

## Роли и права

| Роль | Application | Team | Submission | Mutation Team |
|---|---|---|---|---|
| Владелец individual Application | read/write/submit/withdraw | — | read/write | — |
| Капитан Team | read/write/submit/withdraw | read | read/write | rename/remove/transfer |
| Accepted member | read-only | read | read-only | leave |
| Manager PartnerProgram | read-only | read | read-only | нет |
| Staff/superuser | текущий административный доступ | read | текущий административный доступ | rename/remove/transfer |

Только `TeamMember.status=accepted` дает участнику read-доступ. `invited`,
`declined`, `removed` и `left` являются историей состава и не открывают
Application, Team или Submission.

## Endpoints

- `GET /applications/<application_id>/team/` — детали Team и состав;
- `PATCH /applications/<application_id>/team/` — изменить только `name`;
- `POST /applications/<application_id>/team/leave/` — выйти обычному member;
- `POST /applications/<application_id>/team/members/<member_id>/remove/` —
  перевести member в `removed`;
- `POST /applications/<application_id>/team/transfer-captain/` — передать роль,
  body: `{"member_id": <id>}`.

Team response содержит безопасный профиль пользователя (`id`,
`display_name`, `avatar`) без email, телефона и закрытых полей. Состав
сортируется: капитан, accepted members, исторические статусы, затем дата/id.
Также возвращаются размерные ограничения Program, роль текущего пользователя и
флаги `can_edit`, `can_manage_members`, `can_leave`.

Application response дополнен компактным read-only `team` summary: `id`,
`name`, `captain_id`, `accepted_members_count`, `current_user_role`. Для
individual/undecided значение равно `null`; полный состав остается только в
Team detail.

## Leave, remove и transfer

Все mutation разрешены только для `Application.status=draft` и до
`datetime_application_ends`; отдельный Application deadline не имеет fallback
на legacy-даты. После submit состав, капитан и название заблокированы.

`leave` доступен accepted member с ролью `member`. Статус становится `left`,
строка и `joined_at` сохраняются. Повторный запрос возвращает стабильную
ошибку `team_membership_not_active`. Капитан получает
`captain_transfer_required`.

`remove` доступен капитану/staff для accepted или invited member. Статус
становится `removed`, `joined_at` не очищается. Капитана удалить нельзя;
исторический статус возвращает `team_member_not_removable`.

`transfer-captain` требует accepted member той же Team, Registration этой
Program и отсутствие другой активной собственной/командной Application.
Операция блокирует Program, Application, Team и обе TeamMember, затем атомарно:

1. переводит старого капитана в accepted member;
2. переводит target member в accepted captain;
3. меняет `Team.captain`;
4. меняет `Application.user`.

`Application.created_by` и `Application.project` не меняются. Старый капитан
сохраняет read-доступ как accepted member, но теряет write/submit права.

## Application и Submission read access

`GET /programs/<program_id>/applications/my/` ищет в порядке:

1. собственную активную Application;
2. активную Application accepted-команды;
3. последнюю собственную/командную терминальную Application.

Accepted member и manager могут читать Application detail, список Submission и
Submission detail. PATCH/create/submit/cancel/withdraw остаются owner/captain
или staff operations. Постороннему пользователю объекты не раскрываются.

## Доменные ошибки

Team management service использует стабильные коды:

- `team_permission_denied`;
- `captain_transfer_required`;
- `team_membership_not_active`;
- `team_member_not_found`;
- `team_member_not_removable`;
- `captain_transfer_target_invalid`;
- общие `application_not_editable`, `application_deadline_passed`,
  `team_member_registration_missing`, `active_application_conflict`,
  `captain_member_missing`, `captain_mismatch`.

Permission boundary возвращает 403, скрытый объект — 404, нарушение состояния
или invariant — 400.

## Throttling

Mutation endpoints имеют независимые scoped buckets:

- `team_rename`;
- `team_leave`;
- `team_remove_member`;
- `team_transfer_captain`.

Rate равен `20/min` на scope и пользователя/IP. Throttle локален для Team API:
глобальные DRF settings и существующие application/submission scopes не
изменяются; GET Team отдельным throttle не ограничивается.

## Ограничения MVP

В API намеренно отсутствуют прямой add member, token/link/email invites,
expiry, уведомления и поиск пользователей. Базовый TeamInvite по существующему
`user_id` реализован отдельно. Manager получает только read-access;
organizer review, approve/reject/return, изменение Submission lifecycle и
expert permissions остаются отдельными PR. Frontend и legacy Project flow не
затрагиваются.
