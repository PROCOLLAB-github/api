# Program Participation Policy

## Назначение

Policy хранится в `PartnerProgram` и задает допустимый формат участия,
границы размера команды и отдельный дедлайн подачи `Application`. Эти данные
станут источником истины для будущего транзакционного сервиса создания и
отправки заявок.

В текущем изменении policy валидируется на уровне модели и базы данных, но еще
не применяется существующими Application endpoints. Публичные Program
serializers также намеренно не расширены.

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
Поэтому эту проверку должен выполнять будущий транзакционный domain service
непосредственно перед submit Application.

## Дедлайн Application

`datetime_application_ends` — nullable datetime отдельного процесса заявки.
Он не переиспользует и не меняет semantics следующих legacy-полей:

- `datetime_registration_ends`;
- `datetime_project_submission_ends`;
- `datetime_evaluation_ends`.

Значение `null` означает, что отдельный дедлайн Application не настроен. Метод
`is_application_deadline_passed(at=None)` в таком случае возвращает `False`.
Fallback на регистрацию или сдачу проекта намеренно отсутствует: будущий
domain service должен явно определить поведение при `null`.

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

Существующие Application API, Team API и legacy registration/project flow не
изменены. Policy пока не блокирует create/edit/submit Application, не проверяет
Registration и не разрешает конфликты участия между командами.

Следующий PR должен добавить транзакционный Application/team service. Перед
submit он использует policy для проверки Registration, финального
`participation_mode`, accepted-состава Team и дедлайна без изменения legacy
дедлайнов.
