# Application, Project and Submission RFC

Статус: proposal.

Этот документ описывает целевую доменную модель для React-архитектуры PROCOLLAB. PR является только документационным: он не меняет модели, миграции, serializers, views, endpoints, deploy, nginx, docker-compose или GitHub Actions.

## Цель

PROCOLLAB работает с кейс-чемпионатами, хакатонами, акселераторами и проектными активностями. В текущем backend уже есть `PartnerProgram`, `PartnerProgramUserProfile`, `PartnerProgramProject`, `Project` и `ProjectScore`, но несколько разных бизнес-понятий частично смешаны вокруг `Project`.

Целевая модель должна развести:

- `Application` - организационная сущность участия пользователя или команды в активности.
- `Project` - содержательная карточка проекта, портфолио или рабочая проектная сущность.
- `Submission` - конкретная сдача решения на активность или этап активности.
- `Team` - группа участников внутри активности.
- `Evaluation` / `Score` - оценка эксперта по конкретной сдаче.

Главное правило: `Application` не равна `Project`, а `Submission` не равна ни `Application`, ни `Project`.

## Проблема Текущей Модели

Сейчас `Project` используется слишком широко:

- как обычная карточка проекта в каталоге;
- как портфолио или рабочий проект пользователя;
- как содержательная часть участия в партнерской программе;
- как объект, который подается в программу через `PartnerProgramProject`;
- как объект оценки через `ProjectScore`;
- как часть регистрационного сценария через `PartnerProgramUserProfile.project`.

Такой подход был удобен для раннего продукта, но он плохо масштабируется под React-архитектуру, где нужны отдельные пользовательские экраны: "Моя заявка", "Команда", "Сдачи", "Оценки", "Проект".

Почему нельзя делать `Project = Application`:

- заявка описывает факт участия в конкретной активности, а проект описывает содержание работы;
- заявка может быть без проекта, например регистрация слушателя, участника курса или индивидуального трека;
- один проект может быть использован в разных заявках и конкурсах;
- команда может подать заявку до создания полноценной проектной карточки;
- проект может появиться после сдачи решения, а не до регистрации;
- статусы заявки и статусы проекта живут в разных жизненных циклах;
- заявка содержит ответы формы регистрации, согласия, трек, роль, командный режим, а проект содержит описание идеи, цели, ресурсы, ссылки и достижения.

Если заявка и проект останутся одной сущностью, появятся риски:

- дубли проектов при повторных регистрациях;
- невозможность корректно показать "мою заявку" без создания лишнего проекта;
- смешение прав доступа: участник заявки не всегда должен редактировать проект;
- сложная миграция старого Angular flow;
- неоднозначная оценка: эксперт оценивает сдачу, а не всю проектную карточку навсегда;
- невозможность хранить несколько версий решения;
- сложные ограничения уникальности вокруг `user + program`, `team + program`, `application + stage`;
- дальнейший рост legacy-логики в `projects` и `partner_programs`.

## Целевая Модель Сущностей

### Program / PartnerProgram

Назначение: активность, конкурс, акселератор, хакатон или программа, в которую пользователь может вступить, подать заявку, собрать команду, сдать решение и получить оценку.

Когда создается: менеджером или администратором до старта активности.

Владелец: менеджеры программы и администраторы платформы.

Основные поля:

- `id`
- `name`
- `tag`
- `description`
- `data_schema` или будущая схема формы
- `datetime_registration_ends`
- `datetime_project_submission_ends`
- `datetime_evaluation_ends`
- `datetime_started`
- `datetime_finished`
- `draft`
- настройки конкурсности, публикации проектов и доступности проектов

Связи:

- имеет много `Application`;
- имеет много `Team`;
- имеет много `Submission` через заявки;
- имеет много критериев оценки;
- legacy-связи сохраняются через `PartnerProgramUserProfile` и `PartnerProgramProject`.

Статусы: сейчас ключевой флаг `draft`; в будущем можно добавить явные статусы `draft`, `published`, `registration_open`, `in_progress`, `evaluation`, `finished`, `archived`.

Ограничения от дублей:

- `tag` или slug должны быть уникальными, если используются как публичный идентификатор;
- legacy `PartnerProgramUserProfile` уже имеет `unique_together = (user, partner_program)`;
- legacy `PartnerProgramProject` уже имеет `unique_together = (partner_program, project)`.

Будущие endpoints:

- `GET /programs/`
- `GET /programs/<id>/`
- `GET /programs/<id>/applications/my/`
- `POST /programs/<id>/applications/`

### Application

Назначение: организационная сущность участия пользователя или команды в конкретной активности. Она отвечает на вопрос "кто и на каких условиях участвует в программе".

Когда создается: при сохранении черновика заявки или при отправке заявки на участие.

Владелец: `created_by`; для индивидуальной заявки также `user`; для командной заявки капитан команды или назначенный владелец заявки.

Минимальный MVP-набор полей:

- `id`
- `program`
- `user`
- `team`, nullable
- `created_by`
- `status`
- `form_data`, JSON
- `project`, nullable
- `submitted_at`
- `approved_at`, nullable
- `rejected_at`, nullable
- `withdrawn_at`, nullable
- `created_at`
- `updated_at`

MVP implementation note: `team` is intentionally not added in the first
`Application` model PR because the `Team` model does not exist yet. Until the
Team PR lands, backend validation treats `Application` as an individual
application and requires `user`.

Связи:

- принадлежит одному `Program`;
- принадлежит одному `User` для индивидуального режима;
- может принадлежать одному `Team` для командного режима;
- может ссылаться на `Project`, но не обязана;
- имеет много `Submission`;
- может иметь итоговые решения менеджера или модератора.

Статусы:

- `draft` - черновик, еще не отправлен;
- `submitted` - отправлена на рассмотрение или зафиксирована как участие;
- `approved` - одобрена;
- `rejected` - отклонена;
- `withdrawn` - отозвана пользователем;
- `cancelled` - отменена системой или менеджером.

Ограничения от дублей:

- одна активная индивидуальная заявка на `user + program`;
- одна активная командная заявка на `team + program`;
- активными считать, например, `draft`, `submitted`, `approved`;
- `withdrawn`, `rejected`, `cancelled` могут разрешать повторную подачу только по явному правилу продукта;
- желательно иметь idempotency для создания заявки, чтобы повтор POST не создавал дубль.

Будущие endpoints:

- `GET /programs/<id>/applications/my/`
- `POST /programs/<id>/applications/`
- `GET /applications/<id>/`
- `PATCH /applications/<id>/`
- `POST /applications/<id>/withdraw/`

### Application Подробно

`Application` нужна для разделения регистрационного процесса и проектной сущности.

Она хранит:

- факт участия в активности;
- ответы регистрационной формы;
- индивидуальный или командный режим;
- статус прохождения заявки;
- привязку к проекту, если проект нужен для конкретной активности;
- историю ключевых timestamp-событий.

Почему это не `Project`:

- заявка может существовать без проекта;
- проект может быть создан раньше заявки как портфолио;
- проект может быть создан позже, после отбора или после сдачи;
- заявку можно отклонить, не удаляя проект;
- проект можно редактировать и переиспользовать вне конкретной активности;
- одна карточка проекта может участвовать в нескольких процессах, если это разрешено правилами.

Индивидуальная заявка:

- `user` заполнен;
- `team` пустой;
- `created_by` обычно равен `user`;
- uniqueness строится вокруг `user + program + active_status`.

Командная заявка:

- `team` заполнен;
- `user` может хранить капитана или основного участника, если это нужно для совместимости MVP;
- `created_by` - пользователь, который подал заявку;
- uniqueness строится вокруг `team + program + active_status`.

Заявка с привязанным проектом:

- `project` указывает на существующий или созданный в процессе заявки `Project`;
- заявка остается организационной оболочкой;
- проект остается содержательной карточкой.

Заявка без проекта:

- подходит для программ без проектной части, образовательных активностей, предварительной регистрации, индивидуальных треков;
- `project = null` не является ошибкой, если правила программы это разрешают.

### Team

Назначение: команда участников внутри конкретной активности.

Когда создается: пользователем при командной подаче или менеджером программы.

Владелец: капитан команды; административный доступ имеют менеджеры программы и staff.

Основные поля:

- `id`
- `program`
- `name`
- `captain`
- `status`
- `created_at`
- `updated_at`

Связи:

- принадлежит одному `Program`;
- имеет много `TeamMember`;
- может иметь одну активную `Application`;
- может быть связана с одним или несколькими `Project` только если это разрешено правилами активности.

Статусы:

- `draft`
- `active`
- `locked`
- `archived`

Ограничения от дублей:

- в рамках программы не должно быть нескольких активных команд с одним и тем же пользователем, если правила активности запрещают участие в нескольких командах;
- название команды можно ограничивать уникальностью в рамках программы, если оно используется публично.

Будущие endpoints:

- `POST /teams/`
- `GET /teams/<id>/`
- `PATCH /teams/<id>/`
- `POST /teams/<id>/invite/`

### TeamMember

Назначение: связь `Team` и `User` с ролью и статусом приглашения.

Когда создается: при добавлении капитана, приглашении участника или принятии приглашения.

Владелец: команда; действия обычно выполняют капитан, приглашенный пользователь или менеджер программы.

Основные поля:

- `id`
- `team`
- `user`
- `role`
- `status`
- `invited_by`
- `accepted_at`
- `created_at`
- `updated_at`

Связи:

- принадлежит одной `Team`;
- ссылается на одного `User`;
- через `Team` связан с `Program`.

Роли:

- `captain`
- `member`

Статусы:

- `invited`
- `accepted`
- `declined`
- `removed`

Ограничения от дублей:

- один пользователь не должен иметь два активных `TeamMember` в одной команде;
- один пользователь не должен быть в нескольких активных командах одной активности, если правила активности это запрещают;
- капитан должен быть участником своей команды со статусом `accepted`.

Будущие endpoints:

- `POST /teams/<id>/invite/`
- `POST /team-invites/<id>/accept/`
- `POST /team-invites/<id>/decline/`
- `DELETE /teams/<id>/members/<user_id>/`

### Project

Назначение: содержательная карточка проекта, портфолио или рабочая проектная сущность.

Когда создается: пользователем отдельно в каталоге проектов, при подготовке заявки, при переносе результата активности в портфолио или в legacy flow подачи проекта.

Владелец: лидер проекта; дополнительно могут быть collaborators.

Основные поля в текущей модели уже включают:

- `id`
- `name`
- `description`
- `region`
- `actuality`
- `target_audience`
- `problem`
- `trl`
- `industry`
- `presentation_address`
- `image_address`
- `cover_image_address`
- `leader`
- `draft`
- `is_public`
- `is_company`
- `datetime_created`
- `datetime_updated`

Связи:

- имеет `Collaborator`;
- имеет `ProjectLink`;
- имеет `Achievement`;
- имеет `ProjectGoal`;
- может быть связан с компаниями и ресурсами;
- legacy: связан с программами через `PartnerProgramProject`;
- target: может быть привязан к `Application` или создан из `Submission`.

Статусы:

- в текущей модели используются `draft` и `is_public`;
- в будущем можно добавить более явный жизненный цикл, но не в первом MVP PR.

Ограничения от дублей:

- `Project` не должен создаваться автоматически при каждой попытке регистрации;
- связь проекта с программой должна оставаться уникальной в рамках `program + project`;
- участник проекта уже защищен `UniqueConstraint(project, user)` в `Collaborator`.

Будущие endpoints:

- текущие `/projects/` endpoints сохранить;
- новые application/submission endpoints должны ссылаться на `Project`, а не заменять его;
- возможный будущий endpoint: `POST /submissions/<id>/create-project/`, если продукт решит создавать проект из финальной сдачи.

Project не является заявкой. Он может быть:

- портфолио-объектом пользователя;
- содержанием заявки;
- результатом активности;
- объектом, который можно подать на конкурс проектов;
- объектом, который появляется после `Submission`.

### Submission

Назначение: факт сдачи решения на конкретную активность или этап активности.

Когда создается: участником, капитаном команды или уполномоченным пользователем при сохранении черновика или отправке решения.

Владелец: `submitted_by`; доступ также имеют владелец заявки, команда, менеджеры программы и назначенные эксперты.

Минимальные поля:

- `id`
- `application`
- `program`
- `stage`, nullable
- `submitted_by`
- `title`
- `description`
- `form_data`, JSON
- `links`, JSON/list
- `files` relation
- `status`
- `version`
- `submitted_at`
- `created_at`
- `updated_at`

Связи:

- принадлежит одной `Application`;
- денормализованно хранит `program` для простых выборок и прав доступа;
- может быть связана с файлами и ссылками;
- имеет много `Evaluation`.

Статусы:

- `draft` - черновик решения;
- `submitted` - отправлена;
- `returned` - возвращена на доработку;
- `final` - финальная версия зафиксирована.

Ограничения от дублей:

- выбрать стратегию уникальности: `application + stage + version` или `application + stage + active_status`;
- повторный POST должен быть идемпотентным или защищенным constraint-ами;
- нельзя создавать сдачу для отозванной, отклоненной или отмененной заявки, если правила программы это запрещают.

Будущие endpoints:

- `POST /applications/<id>/submissions/`
- `GET /applications/<id>/submissions/`
- `GET /submissions/<id>/`
- `PATCH /submissions/<id>/`
- `POST /submissions/<id>/submit/`

Submission не является заявкой и не является проектом. Это событие или версия сдачи решения. Эксперт должен оценивать конкретную сдачу, а не абстрактный проект, который может измениться после дедлайна.

### SubmissionFile / SubmissionLink

Назначение: вложения и ссылки, прикрепленные к конкретной сдаче.

Когда создается: во время редактирования черновика или отправки `Submission`.

Владелец: владелец `Submission`.

Основные поля:

- `id`
- `submission`
- `file` или `url`
- `title`
- `kind`
- `created_at`
- `updated_at`

Связи:

- принадлежит одной `Submission`;
- файл может ссылаться на существующий `UserFile`.

Статусы:

- обычно наследуются от `Submission`;
- отдельные статусы нужны только если появится асинхронная проверка файлов.

Ограничения от дублей:

- уникальность `submission + file`;
- уникальность `submission + url`, если ссылки хранятся отдельной таблицей;
- лимиты количества файлов и размера должны задаваться правилами программы.

Будущие endpoints:

- можно включить в `POST/PATCH /applications/<id>/submissions/`;
- отдельные endpoints понадобятся, если нужен независимый lifecycle файлов.

### Evaluation / Score

Назначение: оценка эксперта по конкретной сдаче.

Когда создается: экспертом после назначения на проверку или менеджером при ручной модерации.

Владелец: эксперт; менеджер программы может иметь административный доступ.

Основные поля:

- `id`
- `submission`
- `expert`
- `criteria`
- `score` или `value`
- `comment`
- `status`
- `created_at`
- `updated_at`

Связи:

- принадлежит одной `Submission`;
- ссылается на эксперта;
- ссылается на критерий программы;
- может агрегироваться в итоговый результат заявки или команды.

Статусы:

- `draft`
- `submitted`
- `revised`
- `cancelled`

Ограничения от дублей:

- уникальность `submission + expert + criteria`;
- если оценка хранится одним объектом на эксперта, then uniqueness `submission + expert`;
- текущий legacy `ProjectScore` уже защищает `criteria + user + project`, но target-модель должна оценивать `Submission`.

Будущие endpoints:

- `GET /expert/submissions/`
- `POST /submissions/<id>/evaluations/`
- `PATCH /evaluations/<id>/`

### Certificate / Achievement

Назначение: будущий слой результата участия: сертификат, достижение, бейдж, место или итоговый статус.

Когда создается: после завершения активности, финальной оценки или ручного решения менеджера.

Владелец: пользователь или команда; источник выдачи - программа.

Основные поля:

- `id`
- `program`
- `application`
- `user`, nullable
- `team`, nullable
- `project`, nullable
- `title`
- `kind`
- `status`
- `issued_at`
- `created_at`

Связи:

- может быть связан с `Application`;
- может быть связан с `Project`;
- может создавать или дополнять текущий `Achievement`.

Статусы:

- `draft`
- `issued`
- `revoked`

Ограничения от дублей:

- уникальность зависит от правил программы: например `application + kind` или `user + program + kind`.

Будущие endpoints:

- не входит в MVP;
- возможны `GET /applications/<id>/achievements/` и `GET /users/me/certificates/`.

## Рекомендуемые DB Constraints

Для будущих моделей стоит заложить ограничения на уровне БД, а не только во view/serializer validation:

- одна активная индивидуальная заявка на `user + program`;
- одна активная командная заявка на `team + program`;
- один accepted `TeamMember` на `user + program`, если правила активности запрещают несколько команд;
- уникальность `TeamMember(team, user)` для активных/приглашенных связей;
- защита от дублей `Submission` по `application + stage + version` или другой выбранной версии бизнес-логики;
- защита от дублей `Evaluation` по `submission + expert + criteria`;
- уникальность `SubmissionFile(submission, file)` и `SubmissionLink(submission, url)`, если они вынесены в отдельные таблицы;
- legacy constraints `PartnerProgramUserProfile(user, partner_program)` и `PartnerProgramProject(partner_program, project)` не удалять до отдельной миграции.

Для PostgreSQL желательно использовать partial unique constraints по активным статусам там, где soft lifecycle допускает повторную подачу после `withdrawn`, `rejected` или `cancelled`.

## Endpoint Proposal

MVP endpoints для React-архитектуры:

- `GET /programs/<id>/applications/my/` - получить мою заявку в программе.
- `POST /programs/<id>/applications/` - создать или отправить заявку.
- `GET /applications/<id>/` - получить заявку.
- `PATCH /applications/<id>/` - обновить черновик или разрешенные поля.
- `POST /applications/<id>/withdraw/` - отозвать заявку.
- `POST /applications/<id>/submissions/` - создать или отправить сдачу.
- `GET /applications/<id>/submissions/` - список сдач по заявке.
- `POST /teams/` - создать команду.
- `POST /teams/<id>/invite/` - пригласить участника.
- `POST /team-invites/<id>/accept/` - принять приглашение.
- `GET /expert/submissions/` - список назначенных сдач для эксперта.
- `POST /submissions/<id>/evaluations/` - создать оценку по сдаче.

Эти endpoints должны жить рядом с текущими `/programs/` и `/projects/`, а не заменять их в первом релизе.

## Migration Strategy

Миграция должна быть совместимой со старым Angular flow и текущими backend endpoints.

Порядок:

- не менять существующие `/programs/<id>/register/`, `/programs/<id>/register_new/`, `/programs/<id>/projects/apply/`, `/programs/partner-program-projects/<id>/submit/` сразу;
- сначала добавить новые модели рядом со старыми;
- оставить `PartnerProgramUserProfile` источником совместимости для старого участия;
- оставить `PartnerProgramProject` источником совместимости для старой связи программы и проекта;
- для React использовать новые application/submission endpoints;
- сделать чтение новых сущностей без изменения старых response shapes;
- добавить backfill/mapping только отдельным PR после согласования правил;
- старый `Project` не удалять и не переименовывать;
- старую связь `PartnerProgramProject` не ломать до отдельной миграции данных;
- production/dev deploy и GitHub Actions не менять в рамках доменной миграции.

Возможная стратегия совместимости:

- на первом этапе `Application` может ссылаться на legacy `PartnerProgramUserProfile`, если это нужно для сопоставления;
- новая заявка может опционально создавать или связывать `PartnerProgramUserProfile`, но только после отдельного design review;
- новая `Submission` может опционально ссылаться на legacy `PartnerProgramProject`, если это нужно для переходного периода;
- после стабилизации React flow можно подготовить отдельный migration RFC для удаления дублирующей логики.

## MVP Implementation Plan

PR 1: только этот RFC-документ.

PR 2: `Application` model + migrations + admin + tests. Не менять старые endpoints.

PR 3: API endpoints для `my application`, create/update draft, submit и withdraw. Добавить scoped throttling/idempotency для create/submit, если endpoint публичный или рискованный.

PR 4: React frontend "Моя заявка" на новых endpoints.

PR 5: `Submission` model + API. Описать versioning и constraints до реализации.

PR 6: React submission page.

PR 7: `Team` и `TeamMember` model + API. Сначала минимальный командный сценарий, затем invitations.

PR 8: expert cabinet/evaluation на `Submission`, без расширения legacy `ProjectScore` сверх совместимости.

## What Not To Change

В ближайших PR нельзя:

- делать `Project = Application`;
- переименовывать текущие `/programs/` endpoints без миграции;
- ломать `PartnerProgramProject`;
- ломать `PartnerProgramUserProfile`;
- менять старый Angular flow в одном PR;
- менять production deploy;
- менять dev deploy;
- менять GitHub Actions;
- делать глобальный рефакторинг всех проектов;
- удалять или переименовывать legacy `Project`;
- менять serializers/views/models без отдельного согласования в документационном PR.

## Open Questions

- Должна ли `Application` создаваться сразу как `draft`, или первый MVP создает только `submitted`?
- Может ли пользователь иметь повторную заявку после `rejected` или `withdrawn`, и нужна ли история предыдущих заявок?
- Нужен ли `Application.user` для командных заявок, или достаточно `team + created_by`?
- Должен ли `Project` создаваться внутри заявки, выбираться из существующих проектов или оба сценария нужны сразу?
- Нужны ли этапы программы как отдельная модель `Stage` до реализации `Submission`?
- Оценивает ли эксперт один критерий за раз или отправляет полный набор критериев одной оценочной формой?
- Какой объект считается источником итогового результата: `Application`, последняя `Submission`, агрегированная `Evaluation` или отдельный `Result`?

## Recommended Next PR

Следующий PR: `Application` model + migrations + admin + model tests.

Приоритеты:

- P0: зафиксировать модель `Application`, статусы, ownership и uniqueness для активной заявки.
- P0: добавить тесты на запрет дублей `user + program` и `team + program`.
- P1: добавить admin для чтения и ручной диагностики заявок.
- P1: подготовить mapping к legacy `PartnerProgramUserProfile`, но не включать destructive migration.
- P2: описать будущую модель `Stage` перед реализацией `Submission`, если продукту нужны этапы.
