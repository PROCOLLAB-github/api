# Projects Lifecycle API

## Назначение

DEV-077 добавляет отдельный API рабочего пространства проектов для React-контура. `Submission` и `Project` остаются разными сущностями:

- `Submission` — неизменяемая после отправки версия решения в одной `Application` и одной активности; именно ее оценивает эксперт;
- `Project` — постоянный рабочий результат пользователя или команды, который можно развивать и повторно использовать;
- `Application.project` связывает выбранный Project с участием в конкретной `PartnerProgram`.

Новый lifecycle не переносит Evaluation на `ProjectScore` и не использует `ProjectExpertAssignment`. Источником связанных активностей служит `Project ← Application → PartnerProgram`, а не legacy `PartnerProgramProject`.

## Аудит старого Angular-раздела

В `frontend-angular` изучены domain- и API-слои проекта, каталог и маршруты в `projects/social_platform/src/app`. Старый интерфейс поддерживает:

- каталог и «Мои проекты»;
- карточку, создание, полное редактирование и удаление Project;
- команду, цели, партнеров, ресурсы и вакансии;
- подписки, приглашения, новости, рабочую область и чат;
- привязку проекта к программе и legacy-оценку проекта.

Angular использует legacy endpoints `GET/POST /projects/`, `GET/PUT/PATCH/DELETE /projects/<id>/`, `GET /projects/count/`, `GET /auth/users/projects/`, а также вложенные endpoints коллабораторов, целей, ресурсов, компаний, вакансий, подписок и приглашений. Эти контракты не удаляются и не переименовываются.

В DEV-077 перенесены каталог, список пользователя, базовая карточка, редактирование лидером, связанные активности, выбор существующего Project в Application и создание Project из Submission. Расширенные Angular-сценарии перечислены в разделе DEV-066 и не реализуются частично.

## API

Все новые endpoints требуют аутентификацию.

### `GET /projects/catalog/`

Возвращает только `draft=false` и `is_public=true`. Поддерживает limit/offset pagination, `search` по названию и `industry` по идентификатору. Порядок стабилен: сначала последние обновленные, затем больший id.

### `GET /projects/my/`

Возвращает Project, где текущий пользователь является `leader` либо имеет `Collaborator`. Включает приватные проекты и черновики.

Минимальный list contract:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "Название",
      "short_description": "Краткое описание",
      "image_address": null,
      "cover_image_address": null,
      "draft": true,
      "is_public": false,
      "current_user_role": "leader",
      "can_edit": true,
      "can_use_in_application": true,
      "activities": [
        {
          "id": 10,
          "name": "Активность",
          "application_id": 25,
          "application_status": "submitted"
        }
      ],
      "datetime_updated": "2026-08-01T10:00:00Z"
    }
  ]
}
```

`can_use_in_application=true` только у руководителя. Административный доступ staff не превращает чужой Project в собственный вариант для Application.

### `GET /projects/<project_id>/workspace/`

Дополняет list contract описанием, отраслью, регионом, TRL, сроком реализации, руководителем, коллабораторами и ссылками. Публичный опубликованный Project доступен любому авторизованному пользователю. Private/draft видят руководитель, Collaborator и staff. Для постороннего private/draft скрывается через 404.

Ответ не содержит email, телефон, Application.form_data, Submission или закрытые профильные данные.

DEV-087A добавляет read-only поле `vacancies` на основе существующего
`ProjectVacancyListSerializer`. Оно содержит все вакансии текущего проекта, включая
неактивные и созданные более 90 дней назад; ограничения публичного
`GET /vacancies/` к workspace detail не применяются. Пример элемента:

```json
{
  "id": 15,
  "role": "Backend-разработчик",
  "specialization": null,
  "required_skills": [
    {"id": 3, "name": "Python", "category": {"id": 1, "name": "Backend"}}
  ],
  "description": "Описание вакансии",
  "project": 7,
  "is_active": false,
  "datetime_closed": "2026-08-01T10:00:00Z",
  "response_count": 2,
  "date_create_time": "2026-01-01T10:00:00+03:00"
}
```

### `PATCH /projects/<project_id>/workspace/`

Руководитель и staff могут изменять только:

- `name`, `description`, `region`;
- `actuality`, `problem`, `target_audience`;
- `implementation_deadline`, `trl`;
- `presentation_address`, `image_address`, `cover_image_address`;
- `draft`, `is_public`.

Нельзя менять leader, collaborators, Application, Program, Submission, Evaluation и подписчиков. Неизвестное или запрещенное поле возвращает 400.

### `POST /submissions/<submission_id>/project/`

Создает Project только из `submitted` или `final` Submission. Разрешен владельцу Application (капитану по текущему invariant), staff и superuser. Обычный accepted TeamMember и посторонний получают безопасный 404.

При первом вызове в одной `transaction.atomic`:

1. блокируются Submission и Application;
2. повторно проверяются права и статус;
3. создается private draft Project с leader=`Application.user`;
4. title/description и валидные уникальные HTTP(S)-ссылки переносятся из Submission;
5. accepted TeamMember, кроме капитана, добавляются в `Collaborator`;
6. Project сохраняется в `Application.project`.

Ответ при создании — HTTP 201:

```json
{
  "created": true,
  "project": { "id": 1 }
}
```

Повторный запрос и запрос по другой версии Submission той же Application возвращают существующий Project с HTTP 200 и `created=false`. Если `Application.project` был выбран заранее, endpoint ничего в нем не переписывает: не меняет название, описание, ссылки или команду.

## Application contract и переиспользование

Существующее поле `project` сохраняет тип `number | null`. Ответ обратно совместимо дополнен:

```json
{
  "project": 12,
  "project_summary": {
    "id": 12,
    "name": "Проект",
    "draft": true,
    "is_public": false
  }
}
```

Один Project можно выбрать в нескольких draft Application разных программ. Сервер проверяет, что пользователь является leader (staff имеет административное исключение). После submit serializer запрещает изменение Application, поэтому Project нельзя подменить. Новая Application не копирует Project, а новые Submission не изменяют его автоматически.

## Матрица прав

| Операция | Leader / владелец Application | Collaborator | Accepted TeamMember | Посторонний | Staff / superuser |
| --- | --- | --- | --- | --- | --- |
| Каталог public | Да | Да | Да | Да | Да |
| Свой private/draft Project | Да | Read-only | Только если также Collaborator | 404 | Да |
| Редактирование Project | Да | Нет | Нет | 404/нет | Да |
| Выбор Project в Application | Да | Нет | Нет | Нет | Административно |
| Создание Project из Submission | Да | Нет | Нет | 404 | Да |

## Производительность и совместимость

List/detail selectors используют `select_related` и `Prefetch` для ролей, Application/Program, команды Project и ссылок. Workspace detail отдельно предзагружает вакансии и их навыки, а число необработанных откликов считает в SQL; количество запросов не растёт с количеством вакансий. Тест списка задает query budget, который не растет с количеством Project.

Legacy модели `Project`, `Collaborator`, `PartnerProgramProject`, `ProjectScore`, serializers и `/projects/` сохранены. Подтвержденная ошибка legacy PATCH, который вызывал полный PUT, исправлена на partial update и покрыта regression-тестом. Остальной legacy contract не расширяется новым workspace-ответом.

Изменений моделей и миграций в DEV-077 нет.

## Что остается DEV-066

Следующим этапом остаются React-интерфейс управления вакансиями, чат, рабочая область, новости, подписки, legacy-приглашения, расширенное управление командой Project, передача лидерства и удаление. Также не входят legacy `ProjectScore`, Evaluation lifecycle и автоматическое обновление Project из новых Submission.

## Проверка

Backend PostgreSQL CI должен выполнить новые suites `projects.tests.test_project_workspace_api` и `partner_programs.tests.test_submission_project_api`, затем regression `projects` и `partner_programs`. Локально нельзя заменять PostgreSQL на SQLite: транзакционные блокировки и PostgreSQL constraints должны проверяться в целевой СУБД.
