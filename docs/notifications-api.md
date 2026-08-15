# API внутренних уведомлений

## Назначение

Модуль `notifications` хранит адресные внутриприложенные уведомления о значимых
бизнес-событиях. Он не заменяет email, чат или WebSocket и не создаёт рассылки о
лайках и технических изменениях.

Уведомление создаётся из существующего доменного service/view внутри той же
транзакции, что и бизнес-изменение. Django signals намеренно не используются:
получатели и смысл события определяются в явной точке перехода состояния.

## Модель

`Notification` содержит получателя, nullable-инициатора, тип, категорию,
исторический снимок заголовка и текста, внутренний `action_url`, `event_key`,
`read_at` и время создания.

- удаление получателя каскадно удаляет его уведомления;
- удаление инициатора сохраняет уведомление с `actor=null`;
- `UniqueConstraint(recipient, event_key)` защищает от повторов и гонок;
- индексы `(recipient, -created_at)` и
  `(recipient, read_at, -created_at)` обслуживают историю и непрочитанные;
- `action_url` может быть только относительным маршрутом `/office/`, созданным
  backend-кодом;
- actor в API содержит только `id`, `first_name`, `last_name`, `avatar`.

Email, телефон, дата рождения, права администратора и другие служебные данные в
модели и публичном serializer отсутствуют.

## REST API

Все endpoints требуют авторизации и работают только с уведомлениями текущего
пользователя.

### Список

```http
GET /notifications/?limit=20&offset=0
GET /notifications/?limit=20&offset=0&unread=true
```

`limit` принимает значения `1..100`, `offset` — неотрицательное число. Сначала
возвращаются новые записи, при одинаковом времени — запись с большим `id`.
`unread_count` всегда считает все непрочитанные уведомления пользователя, даже
когда текущая страница отфильтрована или ограничена.

```json
{
  "count": 1,
  "unread_count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 125,
      "type": "vacancy_response_created",
      "category": "vacancy",
      "title": "Новый отклик на вакансию",
      "message": "Получен отклик на вакансию «Frontend-разработчик».",
      "action_url": "/office/projects/7/vacancies/21/responses",
      "read_at": null,
      "created_at": "2026-08-15T12:00:00Z",
      "actor": {
        "id": 15,
        "first_name": "Иван",
        "last_name": "Петров",
        "avatar": null
      }
    }
  ]
}
```

### Счётчик

```http
GET /notifications/unread-count/
```

```json
{"unread_count": 4}
```

### Отметка о прочтении

```http
POST /notifications/<id>/read/
POST /notifications/read-all/
```

Первый endpoint возвращает обновлённое уведомление. Повторный вызов сохраняет
первоначальный `read_at`; чужой или неизвестный `id` скрывается через `404`.
`read-all` обновляет только непрочитанные записи текущего пользователя:

```json
{"updated": 4, "unread_count": 0}
```

## Типы и переходы

| Тип | Получатель | `action_url` |
| --- | --- | --- |
| `project_invite_created` | приглашённый | `/office/projects/invites` |
| `project_invite_accepted` | руководитель проекта | `/office/projects/<id>/edit?section=team` |
| `project_invite_declined` | руководитель проекта | `/office/projects/<id>/edit?section=team` |
| `project_invite_revoked` | приглашённый | `/office/projects/invites` |
| `vacancy_response_created` | руководитель проекта | `/office/projects/<project_id>/vacancies/<vacancy_id>/responses` |
| `vacancy_response_accepted` | кандидат | `/office/vacancies/my` |
| `vacancy_response_declined` | кандидат | `/office/vacancies/my` |
| `team_invite_created` | приглашённый | `/office/team-invites` |
| `team_invite_accepted` | капитан | `/office/applications/<id>/team` |
| `team_invite_declined` | капитан | `/office/applications/<id>/team` |
| `team_invite_revoked` | приглашённый | `/office/team-invites` |
| `application_submitted` | менеджеры программы | `/office/program/<id>` |
| `application_status_changed` | владелец заявки | `/office/program/<id>` |
| `submission_submitted` | менеджеры программы | `/office/program/<id>` |
| `submission_status_changed` | владелец и принятые участники | `/office/program/<id>/submission` |
| `expert_assignment_created` | эксперт | `/office/expert/submissions` |
| `expert_assignment_revoked` | эксперт | `/office/expert/submissions` |
| `evaluation_submitted` | менеджеры программы | `/office/analytics?programId=<id>` |
| `news_comment_created` | владелец источника публикации | `/office/news/<id>` |

При принятии одного отклика остальные ожидающие отклики отклоняются в той же
транзакции, и каждый кандидат получает отдельное уведомление. Для нескольких
менеджеров и участников применяется `bulk_create`. Инициатор исключается из
получателей, а повторный retry использует тот же `event_key`.

## Текущее покрытие lifecycle

В текущем API существуют переходы submit/withdraw для Application,
submit/cancel для Submission, а также приглашения, отклики, назначения,
отправка Evaluation и комментарии. Отдельных публичных операций approve/reject
Application и returned/final Submission на момент DEV-094 нет. Типы
`application_status_changed` и `submission_status_changed` уже закреплены в
контракте и подключаются к фактически существующим переходам; новые lifecycle
endpoints ради уведомлений не добавлялись.

## Границы этапа

Не реализованы WebSocket, push, email/Telegram-рассылки, уведомления о лайках и
чатах, пользовательские настройки, удаление уведомлений и ручные массовые
рассылки. Frontend-центр уведомлений реализуется отдельным этапом после фиксации
и развёртывания backend-контракта.
