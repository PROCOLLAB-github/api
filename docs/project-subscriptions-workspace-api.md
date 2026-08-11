# Project Subscriptions Workspace API

## Назначение

DEV-084.1 добавляет стабильный React workspace-контракт подписки на Project.
Новая модель не создаётся: источником данных остаётся существующая связь
`Project.subscribers`. Legacy API старого Angular-клиента сохраняется без
изменений.

## Контракт

Для авторизованного пользователя доступны методы:

```http
GET    /projects/<project_id>/workspace/subscription/
POST   /projects/<project_id>/workspace/subscription/
DELETE /projects/<project_id>/workspace/subscription/
```

`POST` и `DELETE` принимают только пустой JSON-объект `{}`. Ответ всех методов:

```json
{
  "is_subscribed": true,
  "subscribers_count": 7
}
```

Повторный `POST` сохраняет подписку, а повторный `DELETE` сохраняет отсутствие
подписки. Оба действия идемпотентны и возвращают фактическое текущее количество.

## Видимость и права

- опубликованный публичный Project доступен любому авторизованному пользователю;
- private или draft Project доступен руководителю, collaborator, staff и
  superuser;
- отсутствующий или недоступный Project скрывается одинаковым ответом `404`;
- клиент не может передать пользователя, Project или состояние через payload.

Список подписчиков, email, телефон и другие данные профилей не возвращаются.
Подписка не создаёт Collaborator, Invite, News или другие доменные сущности.

## Workspace detail

`GET /projects/<project_id>/workspace/` дополнительно возвращает:

```json
{
  "is_subscribed": false,
  "subscribers_count": 6
}
```

Selector получает оба значения ORM-аннотациями `Exists` и `Count`. Serializer
не обращается к базе, не загружает пользователей и не создаёт N+1.

## Совместимость и ограничения

Без изменений продолжают работать:

```http
POST /projects/<project_id>/subscribe/
POST /projects/<project_id>/unsubscribe/
GET  /projects/<project_id>/subscribers/
```

На этом этапе не добавляются React UI, email и внутренние уведомления, настройки
частоты, автоматическая подписка команды, список подписчиков и интеграция с
новостной лентой.
