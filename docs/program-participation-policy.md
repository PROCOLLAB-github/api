# Program Participation Policy

## Назначение

Policy хранится в `PartnerProgram` и задает допустимый формат участия,
границы размера команды и отдельный дедлайн подачи `Application`. Эти данные
служат источником истины для транзакционного сервиса создания и отправки
заявок.

Policy валидируется на уровне модели и базы данных и применяется
Application/Team service при create, смене формата и submit. Публичные Program
serializers при этом намеренно не расширены.

## Формат участия

Поле `participation_format` поддерживает три значения:

| Значение | Разрешенные финальные `Application.participation_mode` |
|---|---|
| `individual_only` | Только `individual` |
| `team_only` | Только `team` |
| `individual_or_team` | `individual` и `team` |

`undecided` остается допустимым состоянием черновика Application, но не
считается разрешенным финальным форматом. Метод
`allows_participation_mode(mode)` возвращает `False` и для `undecided`, и для
неизвестного значения.

Runtime default — `individual_only`. Он сохраняет поведение существующих
программ и не включает командные заявки без явной настройки организатора.
После миграции все существующие строки получают это значение.

## Размер команды

`team_min_size` и `team_max_size` применяются только к `team_only` и
`individual_or_team`. Для этих форматов оба поля обязательны, минимальный
размер не может быть меньше двух, а максимальный — меньше минимального.

Для `individual_only` оба значения должны быть `null`. Существующим программам
произвольные границы не назначаются.

Размер команды в будущем рассчитывается только по `TeamMember` со статусом
`accepted`. Капитан имеет accepted-запись `TeamMember` и входит в размер
команды. Фактическое число участников нельзя надежно проверить constraint-ом
одной таблицы: оно зависит от связанных строк и конкурентных изменений.
Поэтому эту проверку выполняет транзакционный domain service непосредственно
перед submit Application.

## Дедлайн Application

`datetime_application_ends` — nullable datetime отдельного процесса заявки.
Он не переиспользует и не меняет semantics следующих legacy-полей:

- `datetime_registration_ends`;
- `datetime_project_submission_ends`;
- `datetime_evaluation_ends`.

Значение `null` означает, что отдельный дедлайн Application не настроен. Метод
`is_application_deadline_passed(at=None)` в таком случае возвращает `False`.
Fallback на регистрацию или сдачу проекта намеренно отсутствует. Domain
service трактует `null` как отсутствие блокирующего дедлайна.

## Validation и database constraints

`PartnerProgram.clean()` привязывает русскоязычные ошибки к
`team_min_size`/`team_max_size` и проверяет соответствие размеров выбранному
формату.

Database constraints дополнительно гарантируют:

- каждый заданный размер не меньше двух;
- `team_max_size >= team_min_size`, когда заданы оба значения;
- у `individual_only` оба размера равны `null`;
- у форматов с командами оба размера заданы.

Constraints защищают данные при обходе model validation, но не проверяют
фактический состав `Team`.

## Текущие ограничения и следующий шаг

Application create, смена participation mode и submit теперь применяют policy,
проверяют Registration, deadline и конфликты участия. Legacy
registration/project flow не изменен.

Публичный Team API дает ролевое чтение и операции rename/leave/remove/transfer.
TeamInvite/accept service использует те же cross-table
проверки без изменения legacy-дедлайнов.
