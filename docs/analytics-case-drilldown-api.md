# Analytics → Case drilldown: production API

## Основание и целевая ветка

Выборочный перенос принятого на DEV PR #760 в `master`.
Production base после fetch: `7b2918ed3d4914e50a5a5fc684706044ba7f5c06`.

Реализация сопоставлена с сохранённым вариантом для master `608bf09` и финальным DEV `2603312`.
Сохранены production-модули `project_case_analytics.py`, `serializers/project_analytics_attention.py`
и `ProjectAnalyticsAttentionPagination`. Сводка и attention остаются на `/project-analytics/`.
Из DEV перенесено усиленное независимое assertion заголовков XLSX.

Модели, endpoints и миграции не добавлялись. Прежние контракты и permissions сохранены;
прочие DEV-функции не переносились.
Кнопка общей выгрузки в Angular Cases удалена по PR #390; API `case_scope=all` сохранён.

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

Общий `project_case_links()` в `services/project_case_analytics.py` обслуживает overview/list/export.
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

## Production rollout и smoke-check

1. Пользователь мержит backend PR в `master`.
2. Пользователь публикует production release или запускает существующий **Release Prod**
   с соответствующими `image_tag` / `deploy_ref`.
3. Проверяет доступность API/admin и здоровье Celery, затем manager selected/without_case list,
   отсутствие доступа у участника/менеджера другой программы, presentation URL/null и scoped XLSX.
4. После успешного API smoke-check пользователь мержит отдельный Angular production PR;
   push в Angular `master` запускает существующий frontend deploy workflow.
5. Проверяет Team, drilldown, отсутствие общей кнопки в Cases, поиск/страницы/презентацию/XLSX,
   mobile и lifecycle карточек.

List и export выпускаются одной backend-версией. Новая версия совместима со старым Angular.
Angular проверяет DTO/scope и не подменяет case export старой общей выгрузкой.
Feature не записывает данные; rollback схемы не требуется. При откате backend после Angular
сначала откатить Angular либо принять временную недоступность case drilldown.
Release/deploy и проверку живой production-среды выполняет пользователь.

