# Независимый review backend: Analytics → Case drilldown

Дата: 28.09.2026. Skill: `procollab-review`.

**Verdict: READY FOR ANGULAR.** Нарушений backend-требований, требующих исправления
перед Angular, не обнаружено. Это не приёмка всей feature и не разрешение на deploy.

## Основание и границы review

Сначала прочитаны утверждённая specification
`procollab-design-system-v1/docs/feature-specs/analytics-case-drilldown.md`, AC01–AC19,
решения Q1–Q4 и [backend contract](../analytics-case-drilldown-api.md).
Implementation report использован как указатель, но его PASS не перенесены автоматически.

Checkout: `api-analytics-case-drilldown`, ветка `feature/analytics-case-drilldown-backend`.
`HEAD` и локальный `origin/master` равны `7b2918ed3d4914e50a5a5fc684706044ba7f5c06`.
Реализация ещё не закоммичена: проверены `git diff 7b2918e` и все новые untracked-файлы.
Diff между двумя commit refs пуст; результат этого review относится к рабочему дереву,
а не к уже опубликованному commit ветки. Remote/deployed SHA в этом review не подтверждался.

Прочитан полный diff трёх изменённых файлов и содержимое трёх новых Python-файлов:
views, exports, общий classifier, query/response serializers, выборка drilldown, tests.
Прослежены модели, permissions, pagination, case-field lookup, XLSX helpers,
legacy list/filter/rates exports, overview и attention endpoints.
Runtime-код и штатные тесты во время review не изменялись. Добавлен этот отчёт и
локальные проверочные скрипт/логи в ignored `.cache/case-tests/`.

## Findings: BLOCKER → MAJOR → MINOR → NOTE

**BLOCKER / MAJOR / MINOR: не обнаружены.**

**NOTE — часть штатных workbook assertions зависит от реализации.**

- Участок: `partner_programs/tests/test_project_case_drilldown.py`, helper `workbook`
  (строки 90–102) импортирует `CASE_PROJECT_COLUMNS`; legacy-тест (строки 463–493)
  строит ожидаемый workbook текущим `build_program_projects_export_file`.
- Почему важно: одновременная ошибочная смена константы/генератора и результата может
  оставить эти конкретные assertions зелёными. При этом прочие проверки содержимого,
  permissions, negative cases и независимые regression-тесты содержательны.
- AC09/AC18 в проверенном diff **не нарушены**: дополнительно проверены буквальные
  заголовки из specification, AST всех прежних функций/classes exporter и workbook
  из исходника `7b2918e`; результаты совпали.
- Минимальное улучшение штатных тестов: фиксировать ожидаемые заголовки литералами
  из контракта и проверять legacy workbook через независимые ожидаемые строки.
  Перенос review-проб в постоянные тесты полезен, но не блокирует Angular.

## Результат проверки контрактов

### API и классификация

- Новый response получается только при `view=case_analytics`. Обычные legacy-запросы
  идут через `super().list()`/прежний exporter. Новые `case_scope`/`case_name` без
  правильного `view` отклоняются с 400; это защита от тихого fallback на all.
- `selected` принимает точный текущий option без trim/casefold. Остальные scopes
  запрещают `case_name`. Неизвестные/дублированные параметры и неверные комбинации
  отклоняются. Export запрещает даже пустые `search/limit/offset/only_submitted`.
- Только list поддерживает поиск по имени (`icontains` после trim), limit 1–100,
  offset >= 0, default 25. Count учитывает поиск; case_metrics относится ко всему bucket.
- `project_case_links()` используется overview/list/export. Missing, blank, whitespace,
  obsolete, nonexact значения относятся к typed `without_case` (`name=null`).
  Настоящий option «Без выбранного кейса» остаётся `selected`; label не служит identity.
- Отсутствие definition/options не скрывает проекты из API. `cases_configured`
  сохраняет прежнее значение «поле существует», а не «есть options».
- Поля/типы страницы и строки соответствуют specification; evaluation metrics нет.

### Scope, permissions и презентация

- Выборка начинается с `PartnerProgramProject` выбранной программы; case field
  также выбирается из неё. Submitted/linked_at/submitted_at берутся с этой связи.
  Сценарий одного Project в двух программах и foreign field value проверен тестами.
- DRF проверяет `IsAdminOrManagerOfProgram` до handler/выборки. Менеджер своей
  программы, staff и superuser разрешены; чужой менеджер, expert-only, participant,
  leader/collaborator без manager-права и посторонний получают 403; anonymous — 401.
- Для отсутствующей программы обычный пользователь получает 403, staff/superuser —
  404, как у этих endpoints на base. Семантика других analytics endpoints не перенесена.
- Дополнительная SQL-проверка отказов установила: проект, program-project и field
  values не читаются до успешной проверки доступа; private presentation/name не утекли.
- Presentation берётся только из `Project.presentation_address`. Проверены внешняя
  ссылка с query/fragment, null, blank и отличный URL самой программы. ProjectDetail
  не вызывается; project/leader загружаются одним `select_related`.
- Сохранена текущая формула `team_size = 1 + Collaborator rows`, включая возможную
  строку лидера. Это не метрика уникальных зарегистрированных участников кейса.

### XLSX и совместимость

- `.xlsx`, лист «Проекты», десять колонок в утверждённом порядке, включая явный
  «Кейс» независимо от label поля. All/selected/without_case выгружают полный scope.
- Порядок — link datetime_created, затем pk. Проверены даты с timezone, submitted
  historical null и stale timestamp несданной связи; для noncompetitive — «Не требуется».
- Полная presentation URL сохраняется текстом. `=`, `+`, `-`, `@`, `#N/A` и табуляция
  не превращаются в формулы: ячейки имеют string type, HYPERLINK не строится.
- Filename проходит существующую sanitization, без CR/LF/path separators, и различает
  all/selected/without_case. После удаления связей уже просмотренного bucket возвращён
  корректный header-only workbook для всех трёх scopes.
- Legacy list/default pagination, generic filter, all/submitted/rates XLSX,
  `/project-analytics/` и attention endpoints покрыты самостоятельно запущенными
  regression-тестами. Старые exporter функции/classes побайтно по AST не изменились;
  workbook all/submitted и overview дополнительно сравнены с исходником base.

## Acceptance Criteria audit

Ссылки T ведут к штатным тестам, P — к дополнительным review-пробам, описанным ниже.
PASS означает полную проверку backend-требования; PARTIAL явно оставляет UI/интеграционную часть.

| AC | Статус | Конкретное evidence |
| --- | --- | --- |
| AC01 | NOT APPLICABLE — Angular | Click/Enter/Space, заголовок и открытие modal относятся к Angular. |
| AC02 | PASS — backend fully verified | `project_case_links` + `case_project_rows`; T2 сравнивает bucket/count, T5 проверяет изоляцию программ, T6 — pagination. |
| AC03 | PARTIAL — backend part verified | `CaseProjectSerializer`, `ProjectCaseRowSerializer`; T1/T7 и P1 проверяют project/presentation/null/blank и JSON/XLSX case. UI placeholders/колонки ещё отсутствуют. |
| AC04 | PARTIAL — backend part verified | `case_project_rows`, safe leader serializer; T1/T13 проверяют team/region/submitted и 0 SQL при сериализации 100 строк. Отображение и browser/network остаются Angular. |
| AC05 | PASS — backend fully verified | `project_case_links`; T2/T4 проверяют missing/blank/obsolete/nonexact и literal label в list/overview/export; P5 сравнивает с base. |
| AC06 | PARTIAL — backend part verified | T3: нет definition/options и пустая программа; без ложных строк. Видимость карточки по Q2 остаётся Angular. |
| AC07 | PASS — backend fully verified | `build_case_projects_export_file`; T6: 32 уникальные строки all, P1: буквальные headers, полная project URL и порядок. |
| AC08 | PASS — backend fully verified | T6: selected с 30 строками при странице 25 и поиске; T2: полный without_case; T9: export отклоняет search/limit/offset. |
| AC09 | PASS — backend fully verified | T11 + запущенные filter/export/overview/attention suites; P5: legacy AST/workbook/overview равны base. Старые serializers/permissions/URLs не изменены. |
| AC10 | PARTIAL — backend part verified | T6: trim+icontains, count, next/previous, encoded option, стабильный порядок, out-of-range. Enter/reset/retry — Angular. |
| AC11 | PASS — backend fully verified | `IsAdminOrManagerOfProgram` и view dispatch; T10: матрица ролей/401/403/404/405; P4: SQL и private payload отсутствуют при отказе. |
| AC12 | PASS — backend fully verified | T5: общий Project, две program links, разные case/submitted/link dates; чужой field игнорируется. Источник дат подтверждён service/serializer/export и P1. |
| AC13 | PARTIAL — backend part verified | T7: raw flags, noncompetitive status XLSX и historical null; serializer/export не придумывают дату. UI status — Angular. |
| AC14 | PARTIAL — backend part verified | T3/T6/T8/T9/T10 и P2: empty/no results/400/401/403/404 остаются разными ответами; loading/error/retry UX — Angular. |
| AC15 | NOT APPLICABLE — Angular | Cancellation, stale response/download и повторный клик. |
| AC16 | NOT APPLICABLE — Angular | Mobile, focus trap, Escape, Mont и visual continuity. |
| AC17 | PARTIAL — backend part verified | `ProjectCaseQuerySerializer`; T9/T4: invalid/unknown/removed option и несовместимые параметры → 400 без all fallback. Guard против старого backend — будущая Angular integration. |
| AC18 | PASS — backend fully verified | T8/T12 и P1/P2: workbook read-back, буквальные headers, URL, ISO даты, filename, literal cells, header-only после удаления данных. |
| AC19 | PASS — backend fully verified | T13: отсутствие writes и 1/100 rows; существующий case test: 1/20 options; P3: 1/100 заполненных cases, queries 4/9/6 без роста. |

## Тесты и независимые evidence

Окружение: Python 3.11.15, Django 4.2.11, отдельный PostgreSQL 18 на loopback:55439,
`procollab.settings_ci`. Использована выделенная тестовая БД; dev/prod не затрагивались.

Самостоятельно выполненная команда:

```text
python manage.py test partner_programs.tests.test_project_case_drilldown partner_programs.tests.test_project_case_analytics partner_programs.tests.test_program_filters partner_programs.tests.test_exports partner_programs.tests.test_program_filter_access partner_programs.tests.test_project_analytics_api partner_programs.tests.test_project_analytics_attention_api --noinput --verbosity 1
```

**101 test, OK, 27.627s, exit code 0.** Это результат текущего review, не прежнего implementation run.
Лог: `.cache/case-tests/independent-review-tests.log`.

T1–T13 — методы [ProjectCaseDrilldownTests](../../partner_programs/tests/test_project_case_drilldown.py):

| ID | Метод |
| --- | --- |
| T1 | `test_selected_projection_and_full_bucket_metrics` |
| T2 | `test_classifier_parity_for_missing_blank_obsolete_and_nonexact_values` |
| T3 | `test_without_case_without_definition_or_options_and_empty_program` |
| T4 | `test_removed_option_is_rejected_and_its_links_move_to_without_case` |
| T5 | `test_same_project_in_two_programs_has_independent_case_submission_and_dates` |
| T6 | `test_pagination_search_exact_encoded_option_and_full_exports` |
| T7 | `test_noncompetitive_null_presentation_and_historical_submission_dates` |
| T8 | `test_empty_case_returns_zero_metadata_and_header_only_workbook` |
| T9 | `test_query_validation_rejects_invalid_and_ambiguous_scope_without_fallback` |
| T10 | `test_permission_matrix_missing_program_and_read_only_methods` |
| T11 | `test_legacy_list_and_all_submitted_xlsx_contracts_stay_unchanged` |
| T12 | `test_xlsx_user_values_are_literal_text_and_filename_is_safe` |
| T13 | `test_constant_queries_for_one_and_one_hundred_rows_and_no_writes` |

Дополнительно создан и запущен отдельный локальный скрипт:

```text
python .cache/case-tests/review_probes.py
```

**5 tests, OK, 2.295s, exit code 0.** Лог: `.cache/case-tests/independent-review-probes.log`.
Скрипт и логи — локальные ignored review-артефакты; они не добавлены в штатный suite.

| ID | Независимая проверка |
| --- | --- |
| P1 | Буквальные headers из spec, изменённый label case, project URL вместо program URL, null/blank, даты и обратный chronological порядок связей. |
| P2 | Сначала прочитать непустой список, удалить связи, затем получить header-only для all/selected/without_case. |
| P3 | 1 строка/1 заполненный case → 100 строк/100 заполненных cases; одинаковый query count. |
| P4 | Anonymous/outsider + все scopes, включая invalid selector: permission error до валидации/чтения private данных; SQL capture. |
| P5 | AST прежних exporter functions/classes совпадает с base; all/submitted workbook и overview сравниваются с исполнением исходника `7b2918e`. |

Реальные замеры P3 (manager, полный request):

| Размер fixture | Overview service | List API | Export API |
| --- | ---: | ---: | ---: |
| 1 project / 1 case | 4 | 9 | 6 |
| 100 projects / 100 cases | 4 | 9 | 6 |

Штатные тесты имеют meaningful assertions по составу строк, точным ролям/ошибкам,
multi-program данным, metadata, пагинации, cell types и отсутствию writes.
Замечание о self-referential expected values ограничено указанным NOTE; остальные
проверки не сведены к вызову того же helper для actual/expected.

## Уровни проверки и следующий этап

- **Checked by source:** spec → полный рабочий diff → модели/permissions/consumers → AC audit;
  новые endpoints/entities/evaluation/UI-права не добавлены.
- **Checked by tests:** 101 regression + 5 независимых review-проб, всего 106 tests;
  оба процесса завершились с exit code 0. Django system checks при запуске тестов успешны.
- **Static checks:** flake8 для всех шести затронутых Python-файлов и `git diff --check` — PASS.
- **Checked by build:** отдельный backend image/package build не запускался.
- **Checked in browser:** не запускалось; UI вне scope текущего этапа.
- **Not checked:** полный backend suite, PostgreSQL 15 CI, live API/данные/deployed SHA,
  нагрузка на production-объёмах, реальное открытие файла в desktop Excel,
  Angular E2E/response guard/keyboard/responsive/визуальная приёмка.

К `procollab-angular` переходить можно на основании этого backend-контракта.
Сохраняются Q1–Q4 и backend-first rollout: export UI включается только после
подтверждения нового list contract, без fallback к legacy all export.
Перед передачей через remote-ветку нужно включить текущие рабочие изменения в commit;
само переключение на нынешний branch HEAD не воспроизводит проверенную реализацию.
Merge и production deploy остаются за пользователем. Angular/React/Figma/DS не менялись.
