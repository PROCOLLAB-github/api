# Целостность legacy Invite (PR B)

База: PR A, `c44bcf089c41c6e8c657a70390e98c46bc2510e7`.
Service: `projects/team_service.py`; models/views/serializers остаются HTTP/ORM-адаптерами.

## Контракт и механизм

Пути и успешные ответы Angular сохранены: POST create → 201, accept/decline → 200,
PATCH/PUT → 200, DELETE pending → 204 с физическим удалением записи.
Все lifecycle writers используют atomic и порядок `Project → Invite → membership`.
Actor проверяется повторно после Project lock. Accept создаёт Collaborator и
завершает Invite в одной транзакции; ошибка любого шага откатывает оба изменения.
Для существующего PUP берётся row lock до создания Collaborator.

До: проверки create вне транзакции; accept не atomic; PATCH мог записать stale
is_accepted; revoke не был согласован с accept. После: service перечитывает Invite
под lock, проверяет pending и записывает только нужные `update_fields`.

| Конфликт | Новый ответ |
| --- | --- |
| Второе pending приглашение | 409 `duplicate_pending_invite` |
| Accept/decline/edit/revoke обработанного Invite | 409 `invite_already_processed` |
| Membership программы отсутствует при create/accept | 409 `not_program_member` |
| Пользователь уже collaborator / leader | 409 `already_project_member` / `already_project_leader` |
| Actor не может управлять / принимать Invite | 403 `not_project_team_manager` / `not_invite_recipient` |
| Запись удалена конкурентным revoke | 404, без Collaborator и без восстановления Invite |

Форма ошибок: `{"code": "stable_code", "detail": "сообщение"}`. Malformed payload
остаётся 400 DRF. Business conflicts create ранее были 400 с полем `user`, теперь 409
с явным code. Новый Angular mapping входит в PR D. Permission публичного legacy API
сохраняется: staff не получает нового права управления Invite.

## Выборочный перенос PROD

Из `master e54545e…`, `invites/workspace_services.py` использованы механизмы atomic,
Project-before-Invite locks, current-membership check и savepoint для unique INSERT.
PROD целиком не переносился. В DEV нет notifications domain; новых внешних side effects
не добавлено. `invited_by`, `is_revoked`, `resolved_at` и nextgen не переносились.
В DEV revoke — DELETE, поэтому active pending = `is_accepted IS NULL`.

## Data audit и migration

Source audit: на DEV есть только migrations 0001/0002 Invite и нет pending constraint.
PROD 0003 содержит другие поля и автоматически отзывает старые дубли; такая стратегия
не переносится, поскольку ТЗ запрещает самостоятельно выбирать победителя.

Новая `0003_legacy_pending_invite_constraint` проверяет дубли и добавляет partial unique
`uniq_legacy_pending_invite(project_id,user_id) WHERE is_accepted IS NULL`.
Откат удаляет constraint, сохраняя все данные. Чтение production DB не выполнялось.

Read-only preflight для DEV перед rollout:

```sql
SELECT project_id, user_id, count(*) AS pending_count,
       array_agg(id ORDER BY id) AS invite_ids
FROM invites_invite
WHERE is_accepted IS NULL
GROUP BY project_id, user_id
HAVING count(*) > 1;
```

Если результат непустой, rollout остановлен: сначала отдельное решение и очистка
конфликтов с разрешением владельца данных, затем применение constraint. Migration
сама ничего не удаляет/не отзывает. Между preflight и constraint БД также проверит
конкурентный INSERT; неуспешная migration откатывается целиком.

При будущем переносе на PROD нужна отдельная адаптация migration graph и predicate
с учётом `is_revoked=False`. Этот DEV constraint нельзя вслепую накладывать поверх
PROD lifecycle: исторические revoked Invite там имеют `is_accepted=NULL`.

## Acceptance criteria

| AC | Наблюдаемый результат | Evidence |
| --- | --- | --- |
| B1 | Injected failure после INSERT не оставляет Collaborator | `test_failure_after_collaborator_insert_rolls_back_everything` |
| B2 | Два одновременных POST → 201/409, одна запись | `test_concurrent_create_has_one_201_and_one_409` |
| B3 | Прямой duplicate INSERT блокируется DB | `test_database_rejects_duplicate_pending_but_allows_history` |
| B4 | Проигранный INSERT constraint → 409, не 500 | `test_insert_constraint_conflict_maps_to_409` |
| B5 | Double accept / accept+decline имеют одного победителя | `InviteConcurrencyTests` |
| B6 | Accept+revoke не оставляют partial state | `test_concurrent_accept_revoke_has_no_partial_state` |
| B7 | Stale PATCH / concurrent PATCH не воскресит pending | `InviteIntegrityTests`, `InviteConcurrencyTests` |
| B8 | Membership удалён перед accept → 409, без mutation | `test_membership_removed_before_accept_returns_409` |
| B9 | Forward/backward сохраняют данные; duplicate preflight не выбирает победителя | `PendingInviteMigrationTests` |

Freeze, multi-link resolver, program-level min/max и exclusivity относятся к PR C.
UI, React, production data, merge и deploy не входят в этот PR.
