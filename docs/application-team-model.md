# Application Team Model

## Назначение

Базовый слой командных заявок разделяет три понятия:

- `Application` — заявка на одну партнерскую программу;
- `Team` — команда, собранная только для этой заявки;
- `TeamMember` — членство пользователя в команде заявки.

Публичного Team API и атомарного service создания команды пока нет. Модели
подготавливают структуру данных для следующих PR, не меняя текущий
индивидуальный API flow.

## Participation mode

В `Application` добавлено поле `participation_mode`:

| Значение | Смысл |
|---|---|
| `undecided` | Формат участия еще не выбран |
| `individual` | Индивидуальная заявка |
| `team` | Командная заявка |

Runtime default временно равен `individual`: существующие API и frontend не
передают новое поле, поэтому все текущие и исторические Application продолжают
работать как индивидуальные. `undecided` должен стать default одновременно с
wizard и запретом submit заявки без выбранного формата.

Миграция `0020_team_application_participation_mode_teammember_and_more`
добавляет поле с default `individual`; Django применяет это значение ко всем
существующим строкам Application.

## Team

`Team` содержит:

- one-to-one `application` с `related_name="team"`;
- необязательное на стадии черновика `name` длиной до 255 символов;
- `captain`;
- `created_at` и `updated_at`.

Team относится к Application, потому что состав команды может различаться в
разных активностях даже при использовании одного Project. Существующий
`projects.Collaborator` описывает постоянного участника Project и намеренно не
переиспользуется как TeamMember.

В первом MVP `Team.captain` обязан совпадать с `Application.user`.
`Team.status`, invite code, token и настройки размера команды не добавлены:
редактируемость будущего Team flow должна выводиться из `Application.status`.

## TeamMember

`TeamMember` содержит:

- `team` и `user`;
- роль `captain` или `member`;
- статус `invited`, `accepted`, `declined`, `removed` или `left`;
- nullable `invited_by`;
- nullable `joined_at`;
- `created_at` и `updated_at`.

Для первоначального captain member `invited_by` остается `null`: капитан не
принимает собственное приглашение, а создается как владелец команды. Статус
`invited` для обычных участников пока является только модельной заготовкой;
механизм TeamInvite в этом PR отсутствует.

При первом сохранении статуса `accepted` модель автоматически заполняет
`joined_at`, если дата не передана. При переходе в `removed` или `left` дата не
очищается и сохраняет момент фактического присоединения.

## Database constraints

На уровне БД обеспечены:

- одна Team на Application через `OneToOneField`;
- уникальность `TeamMember(team, user)`;
- не более одного `accepted` TeamMember с ролью `captain` в Team;
- check: роль `captain` допустима только со статусом `accepted`.

Простым constraint одной таблицы нельзя надежно обеспечить:

- участие пользователя в нескольких Team разных Application одной Program;
- конфликт TeamMember с индивидуальной Application той же Program;
- Registration всех членов команды;
- размер команды;
- блокировку состава после submit.

Эти правила проходят через Application, Team и TeamMember, поэтому требуют
отдельного транзакционного domain service с блокировкой строк.

## Model validation

`Team.clean()` проверяет:

- `Application.participation_mode == team`;
- `Team.captain == Application.user`.

Это запрещает Team для `individual` и `undecided` Application.

`TeamMember.clean()` проверяет:

- captain member имеет статус `accepted`;
- его `user` совпадает с `Team.captain`;
- для первого принятия заполнен `joined_at`.

Наличие captain TeamMember намеренно не проверяется при первом `Team.save()`.
Такая проверка создала бы цикл: Team должна быть сохранена до создания
TeamMember, а TeamMember уже требует сохраненную Team.

## Текущий технический порядок создания

До появления публичного API техническая последовательность выглядит так:

1. создать или обновить Application с `participation_mode=team`;
2. создать Team с captain, совпадающим с `Application.user`;
3. создать accepted TeamMember с `role=captain` и тем же пользователем.

Клиентам нельзя использовать эту последовательность напрямую. Сейчас нет
публичных serializers/views/URLs и транзакционного service, который откатит
частично созданную команду.

## Вне текущего MVP

Следующие PR должны добавить:

- атомарный creation/invariant service;
- проверку Registration и одной активной заявки на Program;
- Team permissions и публичный Team API;
- блокировку состава по Application status;
- TeamInvite, accept/decline/revoke/expire;
- email и внутренние уведомления;
- program policy по формату и размеру команды;
- frontend wizard и вкладку команды.

Project, `projects.Collaborator`, legacy `invites.Invite`, Submission и
существующие Application endpoints этим слоем данных не изменяются.
