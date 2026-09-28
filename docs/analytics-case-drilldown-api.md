# Analytics → Case drilldown: контракт backend

## Основание и целевая ветка

Источник — утверждённая specification `docs/feature-specs/analytics-case-drilldown.md` в Angular repo.
Q1–Q4 закрыты, Figma section `30:1518` утверждена. Полная приёмка UI приведена в связанном Angular PR.

Цель — `dev`, исходная revision `29be99d15ec42d7f69b8e74c402dadc489c6216e`.
Ветка `feature/dev-analytics-case-drilldown-backend` создана от dev; из сохранённого commit
`608bf09` перенесена только feature, без истории master. Имена модулей адаптированы к dev:
`case_analytics.py`, `serializers/attention.py`, `ProgramAttentionPagination`.
Общая аналитика dev остаётся на `/manager-overview/`.
[Исторический независимый review](qa/analytics-case-drilldown-review-2026-09-28.md) относится
к исходному checkout на `7b2918e`, а не к этой базе.

Новые модели, миграции и endpoints не создавались. Case entity и evaluation fields не добавлялись.

## Запросы

```text
GET /programs/{id}/projects/?view=case_analytics&case_scope=selected&case_name={encodedExactOption}&limit=25&offset=0&search={query}
GET /programs/{id}/projects/?view=case_analytics&case_scope=without_case
GET /programs/{id}/projects/?view=case_analytics&case_scope=all

GET /programs/{id}/export-projects/?view=case_analytics&case_scope=selected&case_name={encodedExactOption}
GET /programs/{id}/export-projects/?view=case_analytics&case_scope=without_case
GET /programs/{id}/export-projects/?view=case_analytics&case_scope=all
```

- Case_scope обязателен; case_name обязателен только для selected, в других scopes запрещён.
  Имя — точный текущий option, без trim и изменения регистра.
- Неправильные/повторные/неизвестные параметры, selector без правильного view, неизвестный option,
  пустые/невалидные числа дают 400. Fallback на all отсутствует.
- List: limit по умолчанию 25, диапазон 1–100; offset по умолчанию 0, минимум 0.
  Search ищет подстроку в имени проекта без учёта регистра; внешние пробелы удаляются.
  Порядок: `datetime_created ASC, pk ASC` связи.
- Export не принимает search, limit, offset, only_submitted, включая пустые значения.
  Выгружается полный bucket независимо от поиска и страницы.
- Без параметров нового режима прежние serializer, pagination и XLSX, включая only_submitted,
  сохраняются. Generic filter и rates export не затронуты.

## Ответ списка

Поля страницы: count, next, previous, results, selection, cases_configured,
submission_applicable, case_metrics. Count учитывает search; case_metrics описывают весь bucket:
projects_total, participants_total, submitted, not_submitted. Для all case_metrics = null.
Selection = `{scope, case_name}`; имя вне selected — null.

Пример строки (данные условные):

```json
{
  "program_project_id": 421,
  "project": {
    "id": 81,
    "name": "Название проекта",
    "presentation_address": "https://example.org/presentation.pdf",
    "region": "Москва"
  },
  "case": {"kind": "selected", "name": "Точный option"},
  "leader": {"user_id": 15, "full_name": "Имя Фамилия"},
  "team_size": 3,
  "linked_at": "2026-09-01T10:00:00Z",
  "submitted": true,
  "submitted_at": "2026-09-20T10:00:00Z"
}
```

Without_case: `{kind: "without_case", name: null}`. Презентация/регион nullable и могут быть пустыми.
Отсутствующий leader — null. Для несданной связи/отсутствующей исторической даты submitted_at — null.
Презентация берётся исключительно из `Project.presentation_address`.

## Семантика, права и запросы

Общий `project_case_links()` в `services/case_analytics.py` обслуживает overview/list/export.
Он использует field и links выбранной программы. Missing, blank, whitespace, obsolete и nonexact
попадают в without_case. Настоящий option «Без выбранного кейса» остаётся selected.
Без definition/options все существующие связи попадают в without_case; synthetic rows не создаются.
Cases_configured означает наличие field, как в прежнем overview.

Project/leader загружаются через select_related; team_size — коррелированный aggregate.
Сохраняется legacy формула `1 + число строк Collaborator`, включая сохранённую строку лидера;
она не равна числу зарегистрированных уникальных участников bucket. ProjectDetail fetch и N+1 отсутствуют.

Server-side `IsAdminOrManagerOfProgram` и прежняя дополнительная проверка export сохранены.
Anonymous — 401; participant, leader/team member, expert-only, outsider, foreign manager — 403.
Manager текущей программы и staff/superuser сохраняют API-доступ.
Несуществующая программа: 403 обычному пользователю, 404 staff/superuser, по прежнему порядку
permission/lookup этих endpoints. UI gate staff/superuser не расширяется; контакты/auth-поля не выдаются.

## XLSX

Лист «Проекты». Порядок колонок: №; Название проекта; Кейс; Ссылка на презентацию; Лидер;
Регион; Размер команды; Сдача решения; Дата привязки к программе; Дата сдачи решения.

Without_case отображается как «Без выбранного кейса». Полный URL — literal text, без HYPERLINK.
Пользовательские строки имеют явный string cell type: =, +, -, @ и #N/A остаются текстом.
Прежняя очистка управляющих символов/длины Excel сохранена. Даты — ISO 8601 с timezone, null — пустая ячейка.
Noncompetitive — «Не требуется», raw submitted не меняется.
Если проекты исчезли к экспорту, результат — header-only workbook.

Base name: `projects_{all_cases | without_case | case - NAME} - PROGRAM - DD.MM.YY`.
Content-Disposition использует прежний NFKD sanitizer и UTF-8 filename*.
Angular повторяет этот формат, используя название программы и UTC-дату.
Legacy workbook builders не изменены.

## Проверки на базе dev

28.09.2026: Python 3.11.15, Django 4.2.11, отдельный PostgreSQL 18, ICU locale und,
`procollab.settings_ci`. Рабочие/dev/production БД не использовались.

```text
python manage.py test partner_programs.tests.test_project_case_drilldown partner_programs.tests.test_case_analytics_api partner_programs.tests.test_program_filters partner_programs.tests.test_case_filters_api partner_programs.tests.test_exports partner_programs.tests.test_manager_analytics_api partner_programs.tests.test_attention_analytics_api partner_programs.tests.test_not_submitted_analytics_api partner_programs.tests.test_assignment_analytics_api --noinput --verbosity 1
```

**187 tests PASS**, 45.647 s. Первый прогон на collation C дал три subtest errors в одном
существующем тесте кириллического поиска. Повтор на Unicode collation прошёл;
бизнес-логика поиска ради окружения не менялась.

Покрыты exact/obsolete/blank/nonexact/одноимённый option, without definition/options,
multi-program isolation, permission matrix, pagination/search, invalid query params,
legacy list/filter/export, XLSX contents/даты/порядок/формулы/имена/пустой файл, отсутствие writes.
Overview — 4 запроса; list/export имеют одинаковое число при 1 и 100 строках,
с ограничениями <=10 / <=7. Сериализация 100 строк не делает SQL.
Заголовки нового workbook дополнительно закреплены literal assertion независимо от константы exporter.

Не проверены локально: полный backend suite, PostgreSQL 15, live deployed SHA/data,
production-scale время/память XLSX. GitHub CI фиксируется в PR отдельно.

## Rollout

Backend PR первым попадает в dev; после проверки нового list/export contract — Angular PR.
Старый backend может игнорировать query params: Angular проверяет DTO и scope перед
включением export и повторно непосредственно перед XLSX. Fallback на legacy list/export запрещён.
List и export выпускаются одной backend-версией. Migration не требуется.
Merge, проверку dev и решение о production выполняет пользователь.
