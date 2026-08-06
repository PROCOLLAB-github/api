# React News Feed API

## Назначение

DEV-083.1 добавляет стабильный backend-контракт для будущего раздела
`/office/news`. Он использует общую модель `news.News`, существующие
`core.Like`/`core.View` и новую модель `NewsComment`. Legacy `/feed/` и
контекстные endpoints Angular сохраняют прежние URL и формат ответа.

В `News` по-прежнему хранятся как публикации, так и служебные feed-записи с
пустым текстом. Новый API возвращает только полноценные публикации.

## Источники и список

```text
GET /feed/news/?source=program&search=&limit=10&offset=0
```

Endpoint требует авторизацию. `source` принимает:

- `program` — значение по умолчанию, только новости программ с
  `audience=platform`;
- `project` — новости опубликованных публичных проектов;
- `user` — новости пользователей.

Неизвестный source возвращает `400`. Служебные записи с пустым текстом,
новости private/draft-проектов и participant-only новости программ в список не
попадают. Сортировка: `datetime_created DESC, id DESC`.

`search` обрезается по краям, ограничен 200 символами и выполняет
регистронезависимый поиск внутри выбранной вкладки: по тексту публикации, имени
программы/проекта либо имени и фамилии пользователя.

Ответ использует limit/offset pagination:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 123,
      "source_type": "program",
      "source": {
        "id": 45,
        "name": "Название программы",
        "image_address": "https://example.com/program.png"
      },
      "text": "Текст публикации",
      "files": [],
      "audience": "platform",
      "datetime_created": "2026-08-06T12:00:00Z",
      "datetime_updated": "2026-08-06T12:00:00Z",
      "likes_count": 5,
      "comments_count": 3,
      "views_count": 18,
      "is_user_liked": true
    }
  ]
}
```

Counts и состояние лайка аннотируются в queryset; источники и файлы
prefetch-ятся, поэтому размер страницы не создает N+1.

## Audience программ

`News.audience` принимает:

- `platform` — публикация доступна всем авторизованным пользователям и может
  быть показана во вкладке программ;
- `program_participants` — публикация доступна участникам программы, её
  менеджерам и staff/superuser.

`program_participants` разрешен только для `PartnerProgram`. Новости
пользователей и проектов всегда имеют `platform`.

База ограничивает поле двумя допустимыми значениями. Проверка того, что
`program_participants` относится именно к `PartnerProgram`, выполняется в
model validation и на API-boundary: generic foreign key нельзя надежно
сопоставить с content type в статическом check constraint.

Контекстное создание программы совместимо с Angular:

```text
POST /programs/<program_id>/news/
```

```json
{
  "text": "Текст новости",
  "files": [],
  "audience": "platform"
}
```

Если `audience` отсутствует, создается `program_participants`. Менеджер может
изменить поле через существующий PATCH. Недоступная
внутренняя публикация исключается из контекстного списка и возвращает `404` в
detail.

Data migration переводит все существующие program news в
`program_participants`, а остальные новости — в `platform`.

## Detail, лайки и просмотры

```text
GET  /feed/news/<news_id>/
POST /feed/news/<news_id>/set-liked/
POST /feed/news/<news_id>/set-viewed/
```

Detail возвращает тот же объект, что элемент списка. Он предназначен для
будущего маршрута `/office/news/<news_id>`. Публичная новость программы
доступна авторизованным пользователям, внутренняя — только своей аудитории,
новость проекта — только если проект опубликован и публичен. Недоступный,
несуществующий или служебный объект возвращает `404`.

Лайк:

```json
{ "is_liked": true }
```

```json
{ "is_user_liked": true, "likes_count": 6 }
```

Просмотр не требует payload и возвращает:

```json
{ "views_count": 18 }
```

Обе операции идемпотентны благодаря существующим уникальным ограничениям
`core.Like` и `core.View`. Перед изменением проверяется доступ к публикации.

## Комментарии

```text
GET    /feed/news/<news_id>/comments/
POST   /feed/news/<news_id>/comments/
PATCH  /feed/news/<news_id>/comments/<comment_id>/
DELETE /feed/news/<news_id>/comments/<comment_id>/
```

Список использует limit/offset pagination и сортировку от старых комментариев к
новым. Создание и изменение принимают:

```json
{ "text": "Комментарий" }
```

Пробелы по краям удаляются; пустой текст и текст длиннее 2000 символов
возвращают `400`.

Ответ:

```json
{
  "id": 17,
  "author": {
    "id": 8,
    "name": "Имя Фамилия",
    "image_address": "https://example.com/avatar.png"
  },
  "text": "Комментарий",
  "datetime_created": "2026-08-06T12:00:00Z",
  "datetime_updated": "2026-08-06T12:00:00Z",
  "is_edited": false,
  "can_edit": true,
  "can_delete": true
}
```

Читать и создавать комментарии может любой авторизованный пользователь с
доступом к новости. Редактирует только автор; удаляет автор либо
staff/superuser. `news_id` входит в lookup комментария, поэтому подмена пары
`news_id/comment_id` дает `404`. Удаление новости каскадно удаляет комментарии.

## Обратная совместимость и ограничения

- `/feed/` сохраняет служебные project/vacancy records, старый serializer и
  намеренное исключение новостей программ;
- context API пользователей, проектов и программ сохраняет URL и основные
  поля;
- репостов нет: в продукте это копирование detail-ссылки;
- комментарии плоские, без ответов, лайков, упоминаний и файлов;
- создание публикаций из общей ленты не добавлено: программы продолжают
  публиковать через context endpoint;
- UI ленты, popup, deep-link recovery и копирование ссылки входят в DEV-083.2;
- DEMO-новости, лайки и комментарии входят в DEV-083.3.

Angular-аудит подтвердил: карточка копирует отдельную ссылку, project/profile
detail открывает новость в модальном маршруте, а блок комментариев в карточке
закомментирован и отдельного Angular-flow комментариев нет.
