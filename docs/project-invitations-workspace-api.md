# Project Invitations Workspace API

## Назначение

DEV-079.1 добавляет безопасный backend-сценарий приглашения зарегистрированного
пользователя в рабочее пространство `Project`. После принятия пользователь
становится `Collaborator` этого проекта. `TeamMember`, участник Application,
подписчик проекта и `Collaborator` остаются разными сущностями.

React-интерфейс будет добавлен отдельным этапом DEV-079.2. В этом PR не
добавляются email-приглашения, токены, сроки действия и приглашения
незарегистрированных пользователей.

## Аудит legacy-сценария

Существующая модель `invites.Invite` уже хранит связь `Project` и
зарегистрированного `CustomUser`, роль, специализацию, сообщение и tri-state
`is_accepted`. Angular передает числовой user id, извлеченный из ссылки на
профиль, в `POST /invites/`, получает активные приглашения через
`GET /invites/`, принимает и отклоняет их отдельными action endpoints, а
`DELETE /invites/<id>/` использует как отзыв.

Legacy-контракт `/invites/` сохранен. Новый workspace API использует ту же
сущность, но не требует от React знания legacy-полей `project`, `user` и
`is_accepted`.

## Lifecycle и миграция

В `Invite` добавлены:

- `invited_by` — зарегистрированный отправитель;
- `is_revoked` — отзыв без физического удаления;
- `resolved_at` — время принятия, отклонения или отзыва.

Публичный `status` вычисляется без удаления legacy `is_accepted`:

- `pending` — `is_accepted=null`, `is_revoked=false`;
- `accepted` — `is_accepted=true`;
- `declined` — `is_accepted=false`;
- `revoked` — `is_revoked=true`.

Допустимые переходы:

```text
pending -> accepted
pending -> declined
pending -> revoked
```

Повторный переход завершенного приглашения возвращает `409`. Миграция заполняет
`invited_by` текущим лидером проекта, переносит дату обработки legacy-записей и,
если в старых данных есть несколько pending-записей одной пары Project/User,
оставляет активной только новейшую. Остальные сохраняются как `revoked`.

На уровне БД действуют:

- partial unique constraint для одной pending-записи на `project + user`;
- check constraint, запрещающий одновременно `is_revoked=true` и принятое или
  отклоненное значение `is_accepted`;
- индексы списков по пользователю/проекту и lifecycle-полям.

## API

Все endpoints требуют аутентификацию.

### Список и создание

```http
GET  /projects/<project_id>/workspace/invitations/
POST /projects/<project_id>/workspace/invitations/
```

Список содержит историю только указанного проекта. Доступ имеют лидер проекта,
staff и superuser.

Payload создания:

```json
{
  "recipient_id": 42,
  "role": "Разработчик",
  "specialization": "Backend",
  "message": "Присоединяйтесь к проекту"
}
```

Обязателен только `recipient_id`. Project берется из URL, отправитель — из
аутентифицированного пользователя. Неизвестные и read-only поля отклоняются.

### Входящие приглашения

```http
GET /projects/workspace/invitations/incoming/
```

Возвращает только историю текущего получателя; pending-приглашения идут первыми.

### Поиск кандидатов

```http
GET /projects/<project_id>/workspace/invitations/candidates/?q=<query>
```

Поиск доступен лидеру Project, staff и superuser. `q` обязателен, после удаления
пробелов должен содержать от 3 до 100 символов. Поиск регистронезависимо
проверяет имя, фамилию, полное имя в обоих порядках и начало email, но email в
ответ не включает. Результат ограничен 20 записями и стабильно сортируется по
фамилии, имени и id.

Пример ответа:

```json
[
  {
    "id": 42,
    "display_name": "Иван Петров",
    "avatar": null
  }
]
```

Из результата исключаются неактивные пользователи, лидер и текущие
`Collaborator`, а также получатели действующих pending-приглашений. Отклоненные
и отозванные записи остаются историей и повторный поиск не блокируют. Если
legacy Project напрямую связан с `PartnerProgramProject`, кандидат должен быть
участником этой программы через `PartnerProgramUserProfile`.

Endpoint не создает и не резервирует приглашение. `POST` повторно проверяет все
условия в транзакционном service, поэтому устаревший результат поиска не
позволяет обойти права или eligibility. Для поиска действует отдельный throttle
scope `project_invitation_candidate_search` со скоростью `20/min`.

### Решение и отзыв

```http
POST /projects/workspace/invitations/<invitation_id>/accept/
POST /projects/workspace/invitations/<invitation_id>/decline/
POST /projects/<project_id>/workspace/invitations/<invitation_id>/revoke/
```

Action payload должен быть пустым. Принять или отклонить приглашение может
только получатель. Отозвать pending-приглашение может лидер соответствующего
Project, staff или superuser.

Коды ответа: `201` для создания, `200` для списков и успешных переходов, `400`
для невалидных полей или получателя, `403` для видимого Project без права
управления, безопасный `404` для скрытого Project/чужого приглашения и `409` для
активного дубля либо повторного перехода статуса.

Пример ответа:

```json
{
  "id": 7,
  "project": {
    "id": 10,
    "name": "Проект",
    "draft": true,
    "is_public": false
  },
  "sender": {
    "id": 1,
    "first_name": "Анна",
    "last_name": "Иванова",
    "avatar": null
  },
  "recipient": {
    "id": 42,
    "first_name": "Иван",
    "last_name": "Петров",
    "avatar": null
  },
  "status": "pending",
  "role": "Разработчик",
  "specialization": "Backend",
  "message": "Присоединяйтесь к проекту",
  "created_at": "2026-08-06T12:00:00Z",
  "processed_at": null,
  "updated_at": "2026-08-06T12:00:00Z"
}
```

## Права и ограничения

| Действие | Лидер | Collaborator | Получатель | Посторонний | Staff |
|---|---:|---:|---:|---:|---:|
| Список проекта | Да | Нет | Нет | Нет | Да |
| Поиск кандидатов | Да | Нет | Нет | Нет | Да |
| Создание | Да | Нет | Нет | Нет | Да |
| Входящие | Только свои | Только свои | Только свои | Только свои | Только свои |
| Accept/decline | Только если получатель | Только если получатель | Да | Нет | Только если получатель |
| Revoke | Да | Нет | Нет | Нет | Да |

Нельзя пригласить лидера, существующего `Collaborator`, неактивного или
несуществующего пользователя. Для legacy Project, напрямую связанного с
`PartnerProgramProject`, получатель должен быть участником этой программы — это
повторяет действующий invariant `Collaborator.clean()`.

Приватный Project скрывается от постороннего через `404`; пользователь, который
видит Project, но не управляет им, получает `403`. Ответы не содержат email,
телефон, анкету Application или данные Submission.

Создание, принятие, отклонение и отзыв выполняются в `transaction.atomic` с
блокировками Project и Invite. Принятие и создание `Collaborator` — одна
транзакция. Partial unique constraint закрывает гонку двух создающих запросов.

## Ограничения DEV-079.1

- приглашаются только существующие активные пользователи по `recipient_id`;
- поиск кандидатов возвращает только `id`, `display_name` и `avatar` и не
  заменяет серверную проверку при создании приглашения;
- email, уведомления, invite links и expiration отсутствуют;
- React UI относится к DEV-079.2;
- Angular продолжает использовать legacy `/invites/`;
- `TeamInvite`, `TeamMember`, Application, Submission, подписки, цели и
  достижения не изменяются.
