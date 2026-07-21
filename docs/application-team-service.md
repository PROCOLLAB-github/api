# Application Team Service

## Назначение

`partner_programs.services.application_team` — транзакционный domain service
для индивидуальных и командных `Application`. Он отделяет бизнес-правила от
DRF views и не зависит от HTTP response.

Service предоставляет четыре публичные операции:

- `create_or_get_application()`;
- `change_application_participation_mode()`;
- `validate_team_invariants()`;
- `submit_application()`.

Управление уже созданной Team вынесено в соседний
`partner_programs.services.team_management`: `rename_team()`, `leave_team()`,
`remove_team_member()` и `transfer_team_captain()`. Оба service используют одну
проверку cross-table конфликта под блокировкой Program.

## Доменные ошибки

Все ожидаемые отказы наследуются от `ApplicationTeamServiceError` и содержат
стабильные `code`, `detail` и `field`. Views преобразуют их в DRF
`ValidationError`, но сам service не импортирует DRF.

Основные коды: `registration_required`, `application_deadline_passed`,
`participation_mode_not_allowed`, `participation_mode_undecided`,
`active_application_conflict`, `team_required`, `team_not_allowed`,
`team_has_other_members`, `captain_member_missing`, `captain_mismatch`,
`team_size_invalid`, `team_member_registration_missing` и
`application_not_editable`.

## Создание Application

`create_or_get_application()` выполняет в одной транзакции:

1. блокирует строку `PartnerProgram`;
2. проверяет `PartnerProgramUserProfile` владельца;
3. проверяет `datetime_application_ends` без fallback на legacy-дедлайны;
4. валидирует формат по Program policy;
5. ищет активную собственную Application и accepted-членство в другой Team;
6. создает individual/undecided draft либо team draft;
7. для team атомарно создает `Team` и accepted captain `TeamMember`.

Повторный совместимый запрос возвращает существующую Application с
`created=False`. Отличающийся формат, form data, Project или Team name не
перезаписывает существующий draft скрытым образом и дает конфликт.

`undecided` допустим для draft и не создает Team. Старый API-запрос без
`participation_mode` преобразуется view в `individual`, поэтому существующий
frontend сохраняет прежний формат.

## Смена формата

`change_application_participation_mode()` доступен владельцу или staff для
draft до application deadline:

- `undecided → individual` меняет только поле;
- `undecided/individual → team` создает Team и капитана;
- `individual → undecided` разрешен, пока Team отсутствует;
- `team → individual` удаляет Team только при наличии единственной записи
  accepted-капитана;
- `team → undecided` запрещен, чтобы не удалять состав неявно;
- повторный `team → team` может изменить `team_name`.

PATCH Application вызывает эту операцию до сохранения остальных полей в общей
транзакции. Serializer намеренно не записывает `participation_mode` и
`team_name` напрямую.

## Конфликт активного участия

Активными остаются `draft`, `submitted` и `approved`. Для пользователя service
учитывает обе роли:

- `Application.user`;
- accepted `TeamMember` связанной активной Application той же Program.

Текущая Application исключается при change/submit. Терминальные Application и
членство в другой Program не блокируют новую заявку.

Строка Program блокируется через `select_for_update()` как общая точка
сериализации, после чего блокируются найденные Application/TeamMember. Это
закрывает гонки между операциями, которые проходят через service. Существующая
partial unique constraint дополнительно защищает две собственные активные
Application.

Cross-table invariant нельзя выразить обычным UniqueConstraint. Team transfer
использует ту же проверку под общей блокировкой Program; прямые записи через
admin/model и будущий accept TeamInvite также обязаны проходить domain service.

## Полный Team invariant

`validate_team_invariants()` ничего не изменяет и проверяет:

- Team существует только для `participation_mode=team`;
- `Team.application` и капитан согласованы с Application;
- есть ровно один accepted captain member;
- все accepted-участники имеют Registration этой Program;
- accepted-состав находится между `team_min_size` и `team_max_size`.

Капитан входит в размер команды. `invited`, `declined`, `removed` и `left`
сохраняют историю, но не считаются участниками при submit.

## Submit

`submit_application()` сохраняет текущий owner/staff access contract. Staff не
обходит Registration, Program policy, deadline или Team invariant.

Для draft операция проверяет Registration владельца, application deadline,
финальный формат, cross-table конфликты и Team invariant, затем атомарно
устанавливает `submitted` и `submitted_at`.

Повторный submit уже отправленной Application идемпотентен: он возвращает
текущую запись, не меняет `submitted_at` и не падает из-за дедлайна, который
истек после первой отправки.

## API contract

Application routes сохраняют прежние поля и действия:

- `POST /programs/<id>/applications/` принимает необязательные
  `participation_mode` и write-only `team_name`;
- отсутствие mode означает `individual`;
- response содержит `participation_mode` и компактный read-only `team` summary,
  но не раскрывает полный список TeamMember;
- `PATCH /applications/<id>/` проводит mode/team name через service;
- `POST /applications/<id>/submit/` вызывает транзакционный submit service.

Публичный Team API отдельно описан в `docs/team-permissions-api.md`. Прямого
добавления участника и TeamInvite по-прежнему нет.

## Ограничения concurrency и MVP

Production-база с row-level locking сериализует service-операции одной Program.
SQLite не реализует полноценный `select_for_update`, поэтому автоматический
тест проверяет устойчивую последовательную конфликтную операцию без threading.

Service пока не управляет приглашениями/принятием участников и не блокирует
прямое редактирование моделей через admin. Team permissions, read access и
передача капитанства реализованы отдельным service/API; returned Application и
organizer review отсутствуют.
