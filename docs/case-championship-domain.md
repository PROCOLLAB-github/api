# Домен кейс-чемпионатов PROCOLLAB

Статус: целевая доменная модель и аудит текущей реализации backend.

Актуальность аудита: ветка `master`, коммит `ff0ee65` от 21 июля 2026 года.

Документ развивает `docs/application-project-submission-rfc.md` с учетом уже
реализованных `Application` и `Submission`. Он не является описанием готового
контракта для еще не существующих сущностей команды, приглашений, оценки и
результата.

## 1. Назначение документа

Документ фиксирует целевую модель полного сценария кейс-чемпионата и отделяет
ее от legacy-сценария подачи проекта в партнерскую программу:

```text
Program
  → Registration
  → Application
  → Team / Individual participation
  → Submission
  → Evaluation
  → Result
  → Project reuse
```

Ключевое разделение понятий:

- `Registration` означает присоединение пользователя к активности;
- `Application` описывает участие пользователя или команды в одной активности;
- `Project` является переиспользуемой карточкой проекта;
- `Submission` фиксирует конкретную версию решения по конкретной заявке;
- `Evaluation` относится к зафиксированной сдаче, а не к изменяемому проекту.

В текущем коде `Program` называется `PartnerProgram`, а роль регистрации
выполняет `PartnerProgramUserProfile`. Имена `Application`, `Project` и
`Submission` уже соответствуют целевой терминологии.

## 2. Основные сущности

### Program / Activity

**Назначение.** Активность, программа, хакатон или кейс-чемпионат, внутри
которого действуют регистрация, заявки, команды, сдачи и оценки.

**Связи.** Имеет регистрации, заявки и сдачи; связывается с менеджерами,
экспертами, курсами, материалами и legacy-проектами.

**Что хранит.** Описание и изображения, даты начала и завершения, дедлайны
регистрации, legacy-дедлайн подачи проектов и дедлайн оценки, схему
регистрационных данных, настройки конкурсности и доступности проектов.

**Что не должна хранить.** Ответы конкретного участника, состав команды,
решение или оценку конкретной работы.

**Текущее состояние.** Реализована как `partner_programs.PartnerProgram`.
Специальных настроек формата участия, минимального/максимального размера
команды, дедлайна заявки и отдельного дедлайна решения пока нет.

### Registration

**Назначение.** Факт присоединения пользователя к активности. Дает доступ к
материалам и включает активность в раздел «Мои активности».

**Связи.** Соединяет `User` и `PartnerProgram`; сейчас также может ссылаться на
legacy `Project`.

**Что хранит.** Пользователя, программу, JSON регистрационной формы
`partner_program_data`, необязательный legacy-проект и даты создания/изменения.

**Что не должна хранить.** Статус заявки, формат участия, состав команды,
сдачу решения и оценку. Поле `project` в текущей модели является legacy-связью,
а не частью целевой Registration.

**Текущее состояние.** Отдельной модели `Registration` нет. Ее фактический
аналог — `partner_programs.PartnerProgramUserProfile`. Ограничение
`unique_together(user, partner_program)` не позволяет обычному пользователю
зарегистрироваться в одной программе дважды.

### Application

**Назначение.** Заявка одного владельца или команды на участие в одной
активности.

**Связи.** Принадлежит одному `PartnerProgram`, имеет владельца и автора,
может ссылаться на один `Project`, а также имеет много `Submission`.

**Что хранит.** Ответы формы конкретной программы (`form_data`), статус,
связь с проектом и timestamps ключевых решений.

**Что не должна хранить.** Изменяемое содержимое проекта вместо snapshot,
историю версий решения, экспертные оценки или постоянный состав команды
проекта.

**Текущее состояние.** Реализована как `partner_programs.Application`.
Текущий MVP только индивидуальный: `user` обязателен через `clean()`, а
`participation_mode` и связь с `Team` отсутствуют. `created_by` обязателен.

### Team

**Назначение.** Команда, собранная для одной конкретной заявки.

**Связи.** Принадлежит ровно одной `Application`, имеет капитана и участников.

**Что хранит.** Заявку, название, капитана, при необходимости собственный
статус формирования, даты создания и изменения.

**Что не должна хранить.** Ответы заявки, данные решения, постоянных
collaborators проекта и состояние email-приглашений. `invite_code` допустим
только как временный MVP-механизм; предпочтительнее отдельная `TeamInvite`.

**Текущее состояние.** Отсутствует. `projects.Collaborator` не является
заменой: он связан с долгоживущим `Project`, а не с заявкой на одну программу.

### TeamMember

**Назначение.** Членство пользователя в команде заявки с ролью и состоянием.

**Связи.** Принадлежит одной `Team`, ссылается на `User` и на пригласившего
пользователя.

**Что хранит.** `team`, `user`, `role`, `status`, `invited_by`, `joined_at`,
`created_at`, `updated_at`.

**Что не должна хранить.** Профиль проекта, ответы заявки или независимый
статус самой заявки.

**Текущее состояние.** Отсутствует. `projects.Collaborator` хранит участников
проекта, но не роли и lifecycle команды заявки.

### TeamInvite

**Назначение.** Приглашение в команду заявки для пользователя платформы,
email-адресата или владельца ссылки.

**Связи.** Принадлежит `Team`, ссылается на пригласившего пользователя и,
когда он известен, на приглашенного пользователя.

**Что хранит.** Токен, срок действия, статус, `email` nullable, `user`
nullable, `invited_by` и timestamps.

**Что не должна хранить.** Членство как факт: только принятое приглашение
делает пользователя участником команды.

**Текущее состояние.** Отсутствует. Имеющаяся `invites.Invite` предназначена
исключительно для приглашения в `Project`, хранит tri-state
`is_accepted` и не имеет token, email, expiry или связи с Application Team.

### Project

**Назначение.** Долгоживущая и переиспользуемая карточка проектной идеи или
результата, которая может существовать до, во время и после активности.

**Связи.** Имеет лидера, `Collaborator`, ссылки, достижения, цели, компании и
ресурсы. Может быть связан с несколькими заявками через
`Application.project`; legacy-связь с программами хранится в
`PartnerProgramProject`.

**Что хранит.** Название и описание проекта, проблему, целевую аудиторию,
отрасль, TRL, презентацию, публичность, изображения и долгосрочные данные
проекта.

**Что не должен хранить.** Статус заявки, ответы формы отдельной программы,
команду заявки, версию сдачи или оценку неизменяемого решения.

**Текущее состояние.** Реализован как `projects.Project`. Участники проекта
хранятся в `projects.Collaborator`; `Application.project` уже допускает
переиспользование одного проекта в нескольких заявках.

### Submission

**Назначение.** Конкретная сдача решения по конкретной заявке и этапу.

**Связи.** Принадлежит `Application`, денормализованно ссылается на ее
`PartnerProgram`, имеет автора сдачи и в будущем — оценки и файлы.

**Что хранит.** Название, описание, `form_data`, JSON-список `links`, статус,
`stage_key`, номер версии, дату отправки и audit timestamps.

**Что не должна хранить.** Саму заявку, постоянную карточку проекта, команду
проекта или итоговую экспертную оценку как одно изменяемое поле.

**Текущее состояние.** Реализована как `partner_programs.Submission`.
Несколько версий уже поддерживаются отдельными строками с уникальностью
`application + stage_key + version`; отдельные `Stage`, файлы и оценки
отсутствуют.

### Evaluation

**Назначение.** Оценка конкретной `Submission` конкретным экспертом.

**Связи.** Принадлежит сдаче и эксперту, содержит оценки по критериям и может
агрегироваться в результат заявки.

**Что хранит.** Баллы по критериям, комментарий, итоговый балл, статус и
timestamps.

**Что не должна хранить.** Изменяемую копию проекта или общий рейтинг проекта
вне контекста сдачи.

**Текущее состояние.** Целевой сущности нет. Legacy-модуль `project_rates`
содержит `Criteria`, `ProjectScore` и `ProjectExpertAssignment`, но оценивает
`Project`, а не `Submission`. У `ProjectScore` нет собственного lifecycle и
комментария; уникальность задана по `criteria + user + project`.

### Notification

**Назначение.** Доставляемое и сохраняемое уведомление о приглашении, решении
организатора, возврате заявки или результате.

**Связи.** Ссылается на получателя и доменный объект или событие.

**Что хранит.** Тип, получателя, payload/ссылку, дату создания, состояние
прочтения и, при необходимости, статус доставки.

**Что не должна хранить.** Источник истины о членстве, статусе заявки или
приглашения.

**Текущее состояние.** Доменной модели уведомлений нет. В проекте есть
email-инфраструктура и WebSocket consumer `NotificationConsumer` в модуле
чатов, но они не заменяют persistent-уведомления о TeamInvite.

## 3. Ключевые продуктовые правила

1. **Регистрация не создает заявку автоматически.** Текущий
   `register_user_to_program()` соблюдает это правило.
2. **Заявка относится только к одной активности.** Это обеспечено
   `Application.program`.
3. **Заявка не переиспользуется между программами.** Перенос Application между
   программами запрещен serializer-ом; `program` read-only.
4. **Проект можно использовать в нескольких заявках.** Текущая связь
   `Application.project` не имеет запрета на повторное использование.
5. **Проект является источником данных, но не становится заявкой.** Модели уже
   разделены; автоматического создания Project из Application нет.
6. **Отправленная заявка не меняется вслед за Project.** `form_data` хранится
   отдельно, но полноценный `project_snapshot` отсутствует. Потребители не
   должны считать актуальные поля связанного Project частью отправленной
   заявки.
7. **Команда относится к конкретной заявке.** Это целевое правило; Team еще не
   реализована.
8. **Команда проекта и команда заявки могут различаться.** Будущую Team нельзя
   строить как alias для `Collaborator`.
9. **Пользователь участвует только в одной активной заявке одной программы.**
   Сейчас правило обеспечено только для `Application.user`; будущие члены
   команд этим constraint не покрыты.
10. **В MVP заявку и решение отправляет только капитан.** Сейчас капитана нет;
    действия доступны владельцу индивидуальной Application и staff.
11. **Членами команды считаются только принятые участники.** Это правило должно
    опираться на `TeamMember.status = accepted`, а не на наличие TeamInvite.
12. **Submission относится к конкретной Application.** Уже обеспечено FK и
    проверкой совпадения `Submission.program` с `Application.program`.
13. **Результат Submission можно сохранить как Project или новую версию
    Project.** Это будущий явный пользовательский сценарий; автоматического
    преобразования быть не должно.

## 4. Жизненный цикл регистрации

Целевой flow:

1. Пользователь вызывает `POST /programs/<program_id>/register/`.
2. Backend проверяет `datetime_registration_ends` и отсутствие дублирующей
   регистрации.
3. Создается `PartnerProgramUserProfile` — фактическая Registration.
4. Программа появляется в `GET /programs/?participating=1`, пока ее
   `datetime_finished` не наступил.
5. Application не создается автоматически.
6. Пользователь отдельно выбирает «Создать заявку» и вызывает
   `POST /programs/<program_id>/applications/` при первом сохранении.

Текущая реализация выполняет шаги 1–5. При этом новый Application API пока не
проверяет наличие `PartnerProgramUserProfile` и application-дедлайн. Поэтому
любой авторизованный пользователь технически может создать Application, даже
не зарегистрировавшись в программе, а создание Application не добавляет
программу в `participating=1`.

Регистрационные ответы сейчас находятся в
`PartnerProgramUserProfile.partner_program_data`, а ответы новой заявки — в
`Application.form_data`. До изменения форм необходимо явно определить, какие
поля относятся к присоединению к активности, а какие — к заявке, чтобы не
появилось два неявно конкурирующих источника истины.

## 5. Жизненный цикл Application

### Целевые статусы

| Статус | Значение |
|---|---|
| `draft` | Черновик, доступный для заполнения |
| `submitted` | Заявка отправлена и зафиксирована |
| `returned` | Заявка возвращена организатором на доработку |
| `approved` | Заявка одобрена |
| `rejected` | Заявка отклонена |
| `withdrawn` | Заявка отозвана владельцем/капитаном |
| `cancelled` | Заявка отменена организатором или системой |

### Целевая таблица переходов

| Исходный статус | Действие | Новый статус | Кто | Основные проверки |
|---|---|---|---|---|
| — | Создать черновик | `draft` | Зарегистрированный пользователь | Регистрация открыта; нет другой активной заявки пользователя в Program |
| `draft` | Сохранить | `draft` | Владелец/капитан | Дедлайн не истек; изменяются только разрешенные поля |
| `draft` | Отправить | `submitted` | Владелец/капитан | Registration существует; форма валидна; `participation_mode != undecided`; команда допустимого размера; дедлайн не истек |
| `submitted` | Повторить submit | `submitted` | Владелец/капитан | Идемпотентный ответ без изменения `submitted_at` |
| `submitted` | Вернуть на доработку | `returned` | Организатор | Причина возврата сохранена; программа допускает доработку |
| `returned` | Возобновить редактирование | `draft` | Владелец/капитан | Дедлайн/специальный срок доработки не истек |
| `submitted` | Одобрить | `approved` | Организатор | Проверены заявка и состав команды; заполняется `approved_at` |
| `submitted` | Отклонить | `rejected` | Организатор | Сохраняется причина; заполняется `rejected_at` |
| `draft`, `submitted`, `returned` | Отозвать | `withdrawn` | Владелец/капитан | Отзыв разрешен правилами и сроком; заполняется `withdrawn_at` |
| `approved` | Отозвать | `withdrawn` | Владелец/капитан | Только если политика программы явно разрешает отзыв после допуска |
| Любой нетерминальный | Отменить | `cancelled` | Организатор/система | Сохраняются причина и actor; участник не может подменить отмену отзывом |

`rejected`, `withdrawn` и `cancelled` считаются терминальными для конкретной
Application. Возможность создать после них новую заявку должна быть явной
политикой программы; текущий backend такую повторную заявку разрешает.

### Текущая реализация и отличия

- В `Application.STATUS_CHOICES` есть `draft`, `submitted`, `approved`,
  `rejected`, `withdrawn`, `cancelled`; `returned` отсутствует.
- Активными считаются `draft`, `submitted`, `approved`.
- `PATCH /applications/<id>/` разрешен владельцу только для `draft`.
- `POST /applications/<id>/submit/` реализует идемпотентный переход
  `draft → submitted` и заполняет `submitted_at`.
- `POST /applications/<id>/withdraw/` разрешает отзыв из `draft`,
  `submitted` и `approved`, повторный отзыв идемпотентен.
- Endpoint-ов return, approve, reject и cancel нет. Поля `approved_at` и
  `rejected_at` существуют, но новый API их не заполняет.
- Staff может читать, submit и withdraw любую Application. Обычный менеджер
  программы без `is_staff` в новую permission-модель не включен.
- Создание, submit и withdraw не проверяют Registration, дедлайны или правила
  формы/команды.

## 6. Формат участия

В `Application` требуется целевое поле `participation_mode`:

| Значение | Смысл |
|---|---|
| `undecided` | Формат еще не выбран; черновик можно сохранять, отправлять нельзя |
| `individual` | Индивидуальная заявка; Team отсутствует |
| `team` | Командная заявка; перед submit обязательны Team и капитан |

Правила:

- формат выбирается при создании Application или позже в черновике;
- `undecided` допустим только до submit;
- `individual` не должна иметь Team;
- `team` перед submit должна иметь Team и accepted-капитана;
- менять формат можно только в `draft` и `returned`;
- после `submitted` формат фиксируется;
- переход `team → individual` должен быть запрещен, пока существует команда с
  участниками или необработанными приглашениями, либо выполняться отдельной
  подтверждаемой операцией;
- переход `individual → team` должен создавать Team явным действием, а не
  побочным эффектом чтения Application.

Сейчас `participation_mode` отсутствует, `Application.user` обязателен, а
модельный docstring прямо фиксирует индивидуальный MVP.

## 7. Команда заявки

### Целевая Team

Минимальные поля:

- `application` — one-to-one связь с Application;
- `name`;
- `captain` — пользователь, совпадающий с владельцем командной заявки;
- `status` — только если у команды появится самостоятельный lifecycle;
- `created_at`;
- `updated_at`.

Для первого MVP состояние редактируемости безопаснее выводить из
`Application.status`, а не дублировать его в `Team.status`. Если отдельный
статус все же нужен, сначала следует зафиксировать его переходы и правила
синхронизации. `invite_code` не следует добавлять в Team вместе с будущей
`TeamInvite`, чтобы не получить два источника истины.

### Целевая TeamMember

Минимальные поля:

- `team`;
- `user`;
- `role`: `captain` или `member`;
- `status`: `invited`, `accepted`, `declined`, `removed`, `left`;
- `invited_by`;
- `joined_at`;
- `created_at`;
- `updated_at`.

### Ограничения

- одна Team на одну Application;
- капитан обязательно представлен accepted-записью TeamMember с ролью
  `captain`;
- только один accepted-капитан допустим в одной Team;
- один пользователь не может иметь дублирующиеся членства в одной Team;
- пользователь не может одновременно участвовать в двух активных Application
  одной Program, включая конфликт индивидуальной заявки и TeamMember;
- в минимальном/максимальном размере учитываются только accepted-участники;
- капитан не может уйти, пока не передал роль или не расформировал команду;
- перед submit все accepted-участники должны иметь Registration этой Program;
- после `submitted` состав команды блокируется в MVP; после `returned` он может
  редактироваться только по явно разрешенному правилу.

Часть ограничений нельзя надежно выразить одним Django `UniqueConstraint`,
потому что активность и статус Application находятся через связи
`TeamMember → Team → Application`. Проверки должны выполняться в транзакционном
domain service с блокировкой затрагиваемых строк. На уровне БД все равно нужны
простые ограничения `OneToOne(Team.application)`, uniqueness `team + user`,
условная уникальность капитана и check `captain → accepted`.

## 8. Приглашения

Будущая `TeamInvite` должна поддерживать три канала:

- приглашение существующего пользователя платформы (`user` заполнен);
- приглашение по email (`email` заполнен, `user` может появиться позже);
- приглашение по ссылке с непредсказуемым token.

Минимальные поля:

- `team`;
- `token` с уникальностью и безопасной генерацией;
- `expires_at`;
- `invited_by`;
- `email`, nullable;
- `user`, nullable;
- `status`;
- `created_at`, `updated_at`, а для решения — `responded_at`.

Статусы: `pending`, `accepted`, `declined`, `expired`, `revoked`.

Принятие должно быть идемпотентным и атомарно:

1. блокировать TeamInvite;
2. проверять срок, статус, Registration и отсутствие участия в другой активной
   заявке той же Program;
3. создавать или переводить TeamMember в `accepted`;
4. менять TeamInvite на `accepted`.

Pending TeamInvite не учитывается в размере команды. Если состояния
`invited/declined` одновременно хранятся в TeamMember, service обязан
синхронизировать обе записи; перед реализацией предпочтительно выбрать один
источник истины для приглашения.

Email и внутренние уведомления намеренно не входят в первый PR моделей команды.
Текущую project-specific `invites.Invite` нельзя расширять неявно: ее contract
и permission-логика обслуживают `Project` и старый Angular flow.

## 9. Связь Application и Project

`Application.project` остается nullable. Project можно использовать для:

- выбора существующей проектной идеи;
- явного предварительного заполнения form_data;
- повторного использования одной идеи в разных программах;
- дальнейшего сохранения результата активности.

Application должна независимо хранить:

- `form_data` и program-specific ответы;
- `participation_mode`;
- Team;
- статус и timestamps;
- выбранный трек/кейс;
- согласия.

Текущая связь уже реализована. `ApplicationSerializer` разрешает выбрать
только Project, лидером которого является текущий пользователь, и запрещает
менять связь после выхода заявки из `draft`. Один Project может быть связан с
несколькими Application.

Связь сама по себе не фиксирует данные Project. Будущий `project_snapshot`
нужен, чтобы организатор видел состояние источника на момент submit, даже если
Project позже изменен, скрыт или удален. Snapshot должен создаваться при
первом успешном submit и не обновляться автоматически. До submit обновление из
Project допускается только как явное действие с понятным перечнем
перезаписываемых полей.

`project_snapshot` не обязателен для первого PR моделей Team. Но до запуска
рассмотрения реальных заявок нужно определить его схему, версионирование и
поведение при `Project.on_delete=SET_NULL`.

Legacy-связи сохраняются отдельно:

- `PartnerProgramUserProfile.project` связывает регистрацию со старым flow;
- `PartnerProgramProject` связывает Project с Program и хранит
  `submitted/datetime_submitted`;
- `PartnerProgramFieldValue` хранит ответы старой формы подачи проекта.

Они не должны автоматически создаваться или изменяться новым Application API
без отдельной миграционной стратегии.

## 10. Жизненный цикл Submission

Текущие и целевые статусы совпадают:

| Статус | Значение | Редактирование сейчас |
|---|---|---|
| `draft` | Черновик решения | Разрешено владельцу Application/staff |
| `submitted` | Решение отправлено | Запрещено |
| `returned` | Возвращено на доработку | Разрешено |
| `final` | Финальная версия зафиксирована | Запрещено |
| `cancelled` | Решение отменено | Запрещено |

Правила:

- Submission всегда относится к Application;
- создавать Submission можно только при допустимом статусе Application;
- доступ наследуется от участия в Application, но в Team MVP отправляет только
  капитан;
- редактировать можно только `draft/returned` и до дедлайна;
- отправленные решения остаются читаемыми после дедлайна;
- повторный submit уже отправленной версии должен быть идемпотентным;
- return и final выполняются организатором/экспертом по отдельным действиям;
- отмена владельцем допустима только для `draft/returned`, если продукт не
  зафиксирует другое правило.

Текущий API:

- `GET/POST /applications/<application_id>/submissions/`;
- `GET/PATCH /submissions/<submission_id>/`;
- `POST /submissions/<submission_id>/submit/`;
- `POST /submissions/<submission_id>/cancel/`.

Создание разрешено только для Application в `submitted` или `approved`,
заполняет `program` из заявки и `submitted_by` из request user. Версия по
умолчанию вычисляется как следующая для `application + stage_key`; список
сортируется от новых к старым. Дубликат версии возвращает validation error.

Текущие ограничения:

- нет проверки дедлайна;
- нет manager/expert/team permissions;
- нет действий `return` и `finalize`;
- Application status повторно проверяется при создании, но не при PATCH,
  submit или cancel существующей Submission;
- несколько версий уже технически реализованы, но нет правила выбора текущей
  версии, фиксации оцениваемой версии и создания новой версии после return;
- `stage_key` есть, отдельной модели этапа нет;
- файлы отсутствуют, ссылки временно хранятся JSON-массивом.

## 11. Evaluation

Целевая Evaluation описывается концептуально:

- `submission`;
- `expert`;
- баллы по критериям;
- комментарий;
- итоговый балл;
- статус (`draft`, `submitted`, при необходимости `revised/cancelled`);
- audit timestamps.

До проектирования модели нужно решить, является ли одна Evaluation полной
формой одного эксперта или отдельной записью на каждый критерий. В первом
варианте требуется уникальность `submission + expert`, во втором —
`submission + expert + criterion`.

Существующий `ProjectScore` нельзя считать Evaluation: он связан с изменяемым
Project. `ProjectExpertAssignment` распределяет между экспертами legacy-проекты,
а не Submission. Этот механизм должен продолжать работать для старого flow до
отдельной миграции.

Evaluation, экспертный кабинет, агрегирование баллов и публикация Result не
входят в ближайший этап Team.

## 12. Права ролей

Таблица описывает целевые права. «Редактировать» относится к Application или
Submission в редактируемом статусе; чтение закрытых материалов требует
Registration.

| Роль | Просматривать | Редактировать | Приглашать | Отправлять | Отзывать | Оценивать |
|---|---|---|---|---|---|---|
| Незарегистрированный в Program пользователь | Публичную карточку Program | Нет | Нет | Нет | Нет | Нет |
| Зарегистрированный пользователь без Application | Карточку и материалы Program | Может создать собственный draft | Нет | Нет | Нет | Нет |
| Владелец индивидуальной заявки | Свою Application и Submission | Свои `draft/returned` | Нет | Свою заявку и решение | Свою заявку по правилам | Нет |
| Капитан команды | Заявку, Team и Submission | Заявку, Team и свои `draft/returned` Submission | Да, до блокировки состава | Заявку и решение | Заявку по правилам | Нет |
| Accepted-участник команды | Заявку, Team и Submission | Нет в MVP | Нет | Нет | Может покинуть Team до submit, но не отзывает Application | Нет |
| Организатор/менеджер Program | Все заявки, команды, сдачи и результаты своей Program | Review-поля и разрешенные административные действия | Может помогать по отдельному permission | Возвращает/одобряет/отклоняет/финализирует, но не подменяет капитана | Отменяет, а не выполняет пользовательский withdraw | Не обязан; может администрировать оценки |
| Эксперт | Только назначенные отправленные/финальные Submission | Только свой черновик Evaluation | Нет | Отправляет Evaluation | Нет | Да |

Текущие различия:

- новые Application/Submission endpoints признают владельца по
  `Application.user` и staff/superuser;
- `PartnerProgram.managers` не получают доступ к новым сущностям автоматически;
- участника команды и капитана пока нет;
- эксперт работает только с legacy Project через `project_rates`;
- staff может выполнять submit/withdraw Application и создавать/изменять
  Submission, что является административной возможностью текущего MVP, а не
  окончательной ролевой моделью.

## 13. Текущее состояние реализации

### Сводный audit

| Область | Уже реализовано | Частично | Отсутствует | Комментарий |
|---|---|---|---|---|
| Registration | `PartnerProgramUserProfile`, register endpoints, `participating=1`, deadline и uniqueness | Статус Registration и связь с новым flow | Отдельная модель/явный contract Registration | Application create не требует Registration |
| Application model | Program, user, created_by, form_data, nullable Project, timestamps, partial unique constraint | Только индивидуальный ownership | `participation_mode`, Team, returned, snapshot, review reason | Модель и admin существуют |
| Application API | create/my/detail/patch/submit/withdraw, idempotency create/submit/withdraw, scoped throttle create | Owner/staff access | review endpoints, manager access, deadline/form/team checks | 404 my application корректно означает отсутствие записи |
| Application statuses | Шесть статусов и timestamps submit/approve/reject/withdraw | Переходы draft/submit/withdraw | `returned`, return/approve/reject/cancel actions | approved/rejected могут появиться только вне нового API, например через admin |
| Submission model | Поля MVP, пять целевых статусов, version/stage constraints, model validation | JSON links вместо отдельной модели | Files, Evaluation, Stage | Program согласуется с Application |
| Submission API | list/create/detail/patch/submit/cancel, owner/staff, version allocation, throttling | Только participant/staff flow | manager/expert/team access, return/finalize, deadlines | Создание только для submitted/approved Application |
| Project model | Полноценная карточка, лидер, collaborators, links, цели, компании, ресурсы | Lifecycle через `draft/is_public` | Project version/snapshot | Project остается независимым от Application |
| Application → Project | Nullable FK, reuse, owner validation, immutable после draft | Ручная связь | Prefill mapping и `project_snapshot` | Автоматически Project не создается |
| Team | Нет | Legacy `Collaborator` только для Project | Team целиком | Legacy сущность нельзя переименовать или переиспользовать неявно |
| TeamMember | Нет | `Collaborator` хранит project membership | TeamMember целиком | Нет ролей/статусов команды заявки |
| TeamInvite | Нет | Project-specific `Invite` | TeamInvite token/email/expiry lifecycle | Текущий Invite имеет только `is_accepted` |
| Notification | Email и chat WebSocket infrastructure | Mailing logs не являются inbox | Доменная Notification и пользовательский центр | Не входит в первый Team PR |
| Evaluation | `Criteria`, `ProjectScore`, `ProjectExpertAssignment` для legacy Project | Эксперты и распределенное оценивание проекта | Evaluation по Submission | Нельзя смешивать с ProjectScore без миграции |
| Result | Legacy scores и пользовательские достижения существуют отдельно | Нет единого результата заявки | Result/ranking/publication contract | Требует решения об источнике итогов |
| Deadlines | Registration и legacy project submission/evaluation dates | Поля Program можно переиспользовать только после решения semantics | Проверки в Application/Submission API, отдельные application/solution deadlines | Сейчас новый flow позволяет действия после дедлайнов |
| Permissions | Owner/staff для новых API; manager/expert permissions есть для legacy flow | Staff имеет расширенный доступ | Captain/member, manager и expert permissions для новых сущностей | Нужен общий domain permission layer |
| Constraints | Registration uniqueness; active individual Application; Submission version; Project collaborators | Часть правил в `clean()` и views | Cross-team active participation, captain invariant, team size | Cross-table race требует транзакционного service |
| Admin | PartnerProgram, Registration, Application, Submission, Project, Invite и legacy evaluation зарегистрированы | Admin позволяет ручную диагностику | Team/TeamMember/TeamInvite/Evaluation admin | Admin не заменяет transition services |
| Tests | Подробные model/API tests Application и Submission; regression tests регистрации, project apply, deadlines и permissions | Нет интеграционного end-to-end нового flow | Team/invite/evaluation/result tests | Основной individual Application/Submission MVP хорошо покрыт |

### Актуальные domain endpoints

| Область | Endpoint | Текущее назначение |
|---|---|---|
| Program | `GET /programs/`, `GET /programs/<id>/` | Список и детали активности |
| Registration | `POST /programs/<id>/register/` | Создать PartnerProgramUserProfile текущего пользователя |
| Registration legacy | `POST /programs/<id>/register_new/` | Создать/найти пользователя и зарегистрировать из внешней формы |
| Application | `GET /programs/<id>/applications/my/` | Вернуть активную или последнюю собственную Application; 404, если ее нет |
| Application | `POST /programs/<id>/applications/` | Создать draft или вернуть существующую активную Application |
| Application | `GET/PATCH /applications/<id>/` | Прочитать или изменить draft |
| Application | `POST /applications/<id>/submit/` | Отправить draft |
| Application | `POST /applications/<id>/withdraw/` | Отозвать допустимую Application |
| Submission | `GET/POST /applications/<id>/submissions/` | Список версий или новый draft Submission |
| Submission | `GET/PATCH /submissions/<id>/` | Прочитать или изменить draft/returned |
| Submission | `POST /submissions/<id>/submit/` | Отправить Submission |
| Submission | `POST /submissions/<id>/cancel/` | Отменить draft/returned |
| Legacy Project flow | `POST /programs/<id>/projects/apply/` | Создать и подать отдельный Project в программу |
| Legacy Project flow | `POST /programs/partner-program-projects/<id>/submit/` | Зафиксировать сдачу PartnerProgramProject |
| Legacy evaluation | `GET/POST /rate-project/...` | Список/оценка Project, не Submission |

Новые serializers закрепляют immutable-поля. `ApplicationSerializer` принимает
`form_data` и `project/project_id`, а `SubmissionSerializer` на create принимает
`title`, `description`, `form_data`, `links`, `stage_key`, `version`; на update
— только первые четыре содержательных поля.

### Admin и тесты

- `ApplicationAdmin` показывает Program, owner/creator, status, Project и даты;
- `SubmissionAdmin` показывает Application, Program, submitter, status,
  `stage_key`, version и даты;
- legacy admin продолжает обслуживать Registration, PartnerProgramProject,
  Project, Collaborator, Invite, Criteria, ProjectScore и назначения экспертов;
- Application tests покрывают uniqueness, ownership, immutable fields,
  idempotency, project ownership и throttle;
- Submission tests покрывают доступ, допустимые статусы Application,
  автозаполнение Program/submitter, версии, immutable fields, переходы и
  throttle;
- registration и legacy project tests отдельно покрывают их дедлайны и права.

## 14. Gap analysis

| Требование | Текущее состояние | Требуемое изменение | Приоритет | Рекомендуемый PR |
|---|---|---|---|---|
| Явный формат участия | Все Application индивидуальные | Добавить `participation_mode` с безопасной миграцией | P0 | `feature/application-team-model` |
| Team и TeamMember | Отсутствуют | Добавить модели, admin, базовые constraints и tests | P0 | `feature/application-team-model` |
| Только зарегистрированный создает Application | Не проверяется | Domain service должен проверять PartnerProgramUserProfile | P0 | Application eligibility and lifecycle |
| Одна активная заявка на пользователя с учетом Team | Constraint покрывает только `Application.user` | Транзакционная проверка индивидуальных и командных участий | P0 | Application/team invariants |
| Валидация команды перед submit | Нет Team и program policy | Настройки формата/размера Program и submit validation | P0 | Program participation policy |
| Captain-only actions | Нет капитана | Team-aware permissions для Application и Submission | P0 | Team permissions |
| Team API | Отсутствует | CRUD ограниченного MVP, members, leave/transfer captain | P1 | Team API |
| Полный lifecycle Application | Нет returned/review actions | Добавить return/approve/reject/cancel с reason/audit | P1 | Application review API |
| TeamInvite | Есть только Project Invite | Отдельные token/email/user invites и идемпотентный accept | P1 | TeamInvite model and API |
| Application deadlines | Новый API их не проверяет | Зафиксировать поля Program и проверять create/edit/submit/withdraw | P0 | Application eligibility and lifecycle |
| Submission deadlines и роли | Новый API не проверяет сроки, manager/expert/team | Добавить policy и единый permission layer | P1 | Submission lifecycle hardening |
| Return/finalize Submission | Статусы есть, действий нет | Организаторские endpoints и audit fields/reasons | P1 | Submission review API |
| Semantics версий Submission | Несколько записей и auto-next уже есть | Определить current/final/evaluated version и поведение after return | P1 | Submission version workflow |
| Предзаполнение из Project | Только nullable FK | Явный mapping/copy в Application.form_data | P1 | Application project prefill |
| Неизменяемый Project snapshot | Отсутствует | Создавать snapshot на submit | P1 | Project snapshot |
| Evaluation по Submission | Legacy ProjectScore | Новая модель и API без поломки project_rates | P1 | Submission evaluation |
| Email/in-app приглашения | Нет Team notification flow | Подключить после стабильного TeamInvite | P2 | Team invite notifications |
| Result и сохранение в Project | Нет единого flow | Result contract, ручное create/update/version Project | P2 | Results and project reuse |
| Актуальная модульная документация | RFC есть, module doc не перечисляет новый API | После стабилизации синхронизировать domain/API docs | P2 | Documentation sync |

## 15. Рекомендуемый порядок реализации

1. **`feature/application-team-model`.** Добавить `participation_mode`, Team и
   TeamMember с миграциями, admin, модельными ограничениями и тестами; без API.
2. **Program participation policy.** Зафиксировать разрешенные форматы,
   минимальный/максимальный размер команды и реальные дедлайны Application.
3. **Application/team invariants.** Ввести транзакционный service для проверки
   Registration, конфликтов активного участия, капитана и accepted-состава.
4. **Team permissions and API.** Добавить owner/captain/member/manager access,
   чтение команды, изменение названия, управление участниками и передачу
   капитанства без приглашений по email/ссылке.
5. **Application review API.** Добавить `returned`, return, approve, reject и
   cancel с reason и timestamps; не смешивать с admin-редактированием.
6. **TeamInvite model and API.** Добавить platform/email/link invites,
   accept/decline/revoke/expire и защиту от конфликтов участия.
7. **Invite notifications.** Отдельно подключить email и persistent in-app
   notifications с retry/idempotency.
8. **Frontend participation wizard.** Выбор individual/team/later и создание
   draft только по явному сохранению.
9. **Frontend Team tab.** Состав, accepted/pending состояния, приглашения,
   передача капитанства и блокировка после submit.
10. **Application Project prefill.** Сохранить уже существующую FK, добавить
    явное копирование выбранных полей Project в form_data.
11. **Project snapshot.** Фиксировать согласованный snapshot при submit и
    отображать его организатору.
12. **Submission lifecycle hardening.** Добавить captain/manager/expert rights,
    дедлайн, return/finalize и четкое правило выбора версии. Само поле version
    и DB constraint уже существуют, поэтому повторно «добавлять версии» не
    требуется.
13. **Evaluation.** Добавить assignment/evaluation для Submission и постепенно
    отделить новый flow от legacy `ProjectScore`.
14. **Result and Project reuse.** Зафиксировать публикацию результата и только
    по подтверждению пользователя создавать Project или новую версию Project.

Каждый PR должен содержать собственные model/API tests и не менять legacy
endpoints без отдельной миграционной задачи.

## 16. Первый рекомендуемый coding PR

Ветка: `feature/application-team-model`.

### Точный scope

1. Добавить в `Application` поле `participation_mode` с choices
   `undecided/individual/team`.
2. Сохранить `Application.user` обязательным и трактовать его как
   владельца/капитана в первом Team MVP. Это сохраняет текущие query и
   permissions до отдельного Team API PR.
3. Для существующих Application выполнить data migration в `individual`.
   Пока current API не принимает и не валидирует новый выбор, безопасный
   runtime default также должен оставаться `individual`; переход default на
   `undecided` следует делать вместе с API/UI и запретом submit undecided.
4. Добавить `Team` с one-to-one `application`, `name`, `captain`,
   `created_at`, `updated_at`. В первом PR не добавлять `invite_code`.
5. Не добавлять `Team.status`, пока не определен самостоятельный lifecycle:
   блокировку состава в MVP выводить из `Application.status`.
6. Добавить `TeamMember` с `team`, `user`, `role`, `status`, `invited_by`,
   `joined_at`, `created_at`, `updated_at` и указанными выше choices.
7. Добавить DB constraints:
   - одна Team на Application через OneToOne;
   - уникальность `team + user`;
   - не более одного accepted TeamMember с ролью captain на Team;
   - captain-role допустима только со статусом accepted.
8. Добавить model validation:
   - Team допустима только для `participation_mode = team`;
   - `Team.captain` совпадает с `Application.user` в первом MVP;
   - captain TeamMember совпадает с `Team.captain`;
   - `individual` Application не может иметь Team.
9. Не требовать наличия captain TeamMember непосредственно при первом
   `Team.save()`: это создает циклическую последовательность создания. Полный
   invariant проверять после атомарного создания Team + captain member в
   будущем domain service и обязательно перед submit Application.
10. Зарегистрировать Team и TeamMember в Django admin с фильтрами по Program,
    статусу и роли.
11. Добавить model/migration tests для choices, миграции существующих данных,
    one-to-one, uniqueness и validation.

### Намеренно вне scope

- serializers, views, URLs и новые endpoints;
- TeamInvite, token, email и уведомления;
- поиск пользователей;
- frontend;
- изменение Application submit/withdraw contract;
- `returned` и organizer review actions;
- Program policy fields и дедлайны;
- cross-table enforcement «один пользователь — одна активная заявка Program»;
- Project prefill/snapshot;
- Submission, Evaluation и Result;
- изменение `projects.Collaborator`, `invites.Invite`, legacy registration и
  legacy project submission;
- deploy, settings, Docker, nginx и workflows.

Такой scope дает самостоятельный, мигрируемый слой данных без преждевременного
публичного API. Следующий PR обязан добавить транзакционный creation/invariant
service до того, как Team станет доступна клиентам.
