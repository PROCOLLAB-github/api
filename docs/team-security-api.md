# Legacy-команда: авторизация и контролируемые ошибки (PR A)

База: `dev 0976fdf9ff08e85922a38508509fc31347ef1fd3`.
Область: Project / Collaborator; без новых конкурсных правил и изменений схемы.

## До изменения и целевое поведение

`SwitchLeaderRole.patch` и `ProjectCollaborators.delete` обходили object permission.
Публичность проекта позволяла постороннему удалить участника, а смена лидера была
доступна постороннему даже для приватного проекта. Проверки должны выполняться
до mutation в HTTP-слое и повторно на заблокированном Project внутри service.

Управляет командой только текущий лидер. Read involvement, staff и участие в
команде сами по себе не дают права удалить другого участника или сменить лидера.
Участник по-прежнему может выйти сам; лидер сначала должен передать лидерство.

## API до / после

Все существующие пути, GET и успешные ответы `204` сохранены.
Ошибки service имеют форму `{"code": "stable_code", "detail": "сообщение"}`.

| Операция / ситуация | До | После |
| --- | --- | --- |
| PATCH `/projects/{id}/collaborators/{user}/switch-leader/`, outsider | 204 | 403 `not_project_team_manager` |
| DELETE `/projects/{id}/collaborators/?id={user}`, outsider | 204 на публичном проекте | 403 `not_project_team_manager` |
| Удаление лидером самого себя | 500 | 422 `leader_cannot_leave` |
| Удаление отсутствующего участника | 500 | 422 `collaborator_not_found` |
| Некорректный / отсутствующий query `id` | 500 | 422 `invalid_collaborator_id` |
| POST direct add | 500 AttributeError | 405 `direct_member_add_unsupported` после авторизации |
| Смена на текущего лидера | 422 | 422 `already_project_leader` |
| Несуществующий проект | 404 | 404 |

Direct add не поддерживался рабочей реализацией; добавление через Invite сохраняется.
Для операций применяется порядок locks `Project → Collaborator` внутри atomic.
Лидер повторно проверяется после получения Project lock, поэтому разрешение,
выданное до concurrent switch, не позволяет бывшему лидеру продолжить mutation.

## Acceptance criteria и evidence

| AC | Предусловие / действие / результат | Проверка |
| --- | --- | --- |
| A1 | Outsider switch public/private → 403, лидер сохранён | `test_outsider_cannot_remove_or_switch_public_or_private_project` |
| A2 | Outsider remove public/private → 403, участник сохранён | тот же тест |
| A3 | Read collaborator не получает manage permission | `test_read_involvement_does_not_grant_team_management` |
| A4 | Лидер может удалить участника и передать лидерство | существующий `ProjectCollaboratorRegressionTests` |
| A5 | Self-remove, missing, malformed ID, direct add → controlled 4xx | `TeamSecurityTests` |
| A6 | Вызов service без HTTP gate также проверяет actor | `test_service_rechecks_actor_without_http_permission_gate` |
| A7 | Бывший лидер после switch теряет manage permission | `test_former_leader_cannot_manage_after_switch` |

## Совместимость и границы

Angular остаётся consumer существующих маршрутов. Ошибочный Angular DELETE query
теперь даёт 422 вместо 500; исправление самого URL относится к отдельному PR D.
React не исследовался и не менялся согласно ТЗ. UI / Design System не затронуты.
Freeze, min/max, program context и exclusivity относятся к PR C; lifecycle Invite —
к PR B. Migrations и DB constraints отсутствуют. Production data не изменяются.
