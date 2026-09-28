# Analytics case drilldown: backend contract and handoff

## Scope and baseline

Source: approved `docs/feature-specs/analytics-case-drilldown.md` in the PROCOLLAB
design-system/frontend checkout; Q1–Q4 and Figma section `30:1518` are approved.
This document records the backend implementation, not completion of the UI feature.

Preflight on 2026-09-28 fetched `origin/master` at
`7b2918ed3d4914e50a5a5fc684706044ba7f5c06`. The implementation branch is
`feature/analytics-case-drilldown-backend`, based on that revision in a separate
checkout. Since the specification's `2fbc7225` reference, master changed expert
admin code/tests only. Relevant models, views, permissions, exporters and tests
were inspected again. Deployed SHA remains unconfirmed.

No models, migrations, endpoints, frontend, Figma or Design System changes.
No evaluation fields. Existing `IsAdminOrManagerOfProgram` is retained for both
endpoints; staff/superuser API access remains as before, with no UI access changes.

## Opt-in requests

```text
GET /programs/{id}/projects/?view=case_analytics&case_scope=selected&case_name={encodedExactOption}&limit=25&offset=0&search={query}
GET /programs/{id}/projects/?view=case_analytics&case_scope=without_case
GET /programs/{id}/projects/?view=case_analytics&case_scope=all

GET /programs/{id}/export-projects/?view=case_analytics&case_scope=selected&case_name={encodedExactOption}
GET /programs/{id}/export-projects/?view=case_analytics&case_scope=without_case
GET /programs/{id}/export-projects/?view=case_analytics&case_scope=all
```

- `case_scope` is required. `case_name` is required only for `selected` and forbidden
  otherwise; it must equal a current option exactly, without trimming/case folding.
- Missing/unknown view with a case selector, unknown/duplicate parameters, invalid
  options, blank/invalid numbers or incompatible selectors return 400, never all.
- List: `limit` defaults to 25, range 1–100; `offset` defaults to 0, minimum 0.
  `search` trims outer whitespace and matches project name case-insensitively.
  Ordering is link `datetime_created ASC, pk ASC`.
- Export rejects `search`, `limit`, `offset`, `only_submitted`, even empty values.
  The frontend must omit them: export always contains the complete selected bucket.
- Existing requests without case-mode parameters use the original serializer,
  pagination and exports, including `only_submitted`; generic filters/rates are unchanged.

Page fields: `count`, `next`, `previous`, `results`, `selection`, `cases_configured`,
`submission_applicable`, `case_metrics`. `count` includes search; metrics always
describe the full bucket (`projects_total`, `participants_total`, `submitted`,
`not_submitted`). In `all`, metrics are null; unique participants are not summed.
`selection` is `{scope, case_name}`, with null name outside `selected`.

Each result contains:

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

Example data only. `without_case` returns `{kind: "without_case", name: null}`.
Presentation/region may be null or blank. Missing leader is handled as null.
For unsent links or historical missing timestamps, `submitted_at` is null.

## Shared classification and export

`project_case_links()` in `services/project_case_analytics.py` classifies only
`PartnerProgramProject` links in the requested program, using that program's case
field. Overview/list/export share it. Missing, blank, whitespace, obsolete and
nonexact values all map to `without_case`. A real option named
«Без выбранного кейса» remains a separate selected bucket. No case definition or
no options means all existing links are in `without_case`; no synthetic rows.
`cases_configured` retains overview semantics: field existence, not nonempty options.

`case_project_rows()` loads project/leader with `select_related` and annotates team
size with a correlated aggregate. No per-row queries or ProjectDetail fetches.
Legacy team-size semantics (`1 + Collaborator rows`, including a stored leader row)
are intentionally retained, distinct from registered unique case participants.

XLSX sheet «Проекты», columns:

1. №
2. Название проекта
3. Кейс
4. Ссылка на презентацию
5. Лидер
6. Регион
7. Размер команды
8. Сдача решения
9. Дата привязки к программе
10. Дата сдачи решения

Full `Project.presentation_address` is stored as literal text; no hyperlink formula.
All user text gets explicit string cell type, including `=`, `+`, `-`, `@`, `#N/A`.
Existing control-character/Excel-length sanitization is reused. Dates are ISO 8601
with timezone; missing values are blank. Noncompetitive status is «Не требуется»,
without changing raw flags. Empty buckets produce a workbook with headers only.
Filename distinguishes all/selected/without_case and uses the existing safe
Content-Disposition helper. Legacy workbook builders are unchanged.

Anonymous requests return 401; participant, project leader/team member, expert-only,
outsider and foreign manager return 403. Program manager and staff/superuser retain
access. Missing program returns 403 to ordinary users and 404 to staff/superuser,
following existing endpoint lookup/permission order. No private user serialization.

## Requirement audit

PASS below means the backend portion only. UI acceptance remains unverified.

| AC | Verdict and evidence |
| --- | --- |
| AC01 | Angular pending: click/keyboard/modal/title. |
| AC02 | PASS: classifier parity and pagination fixtures compare full bucket counts and scoped links. |
| AC03 | Backend PASS: project/presentation/case projection and nulls; UI columns/placeholder pending. |
| AC04 | Backend PASS: safe leader/team/region/submission projection; 100-row serializer makes zero queries; UI pending. |
| AC05 | PASS: missing/blank/obsolete/nonexact/literal-label overview/list/export parity. |
| AC06 | Backend PASS: no definition/options and empty program; Angular visibility pending. |
| AC07 | PASS: all XLSX includes all 32 fixture links once with Case and presentation. |
| AC08 | PASS: 30-row selected export includes every page; search is rejected by export; without_case parity. |
| AC09 | Backend PASS: legacy payload/pagination/all/submitted exports and 88 existing regression tests; frontend unmodified. |
| AC10 | Backend PASS: stable ordering, URL encoding, search/count/pagination; Enter/reset/retry pending in Angular. |
| AC11 | PASS: direct API permission matrix, missing-program and read-only-method assertions. |
| AC12 | PASS: one project in two programs uses independent case/submission/dates; foreign field ignored. |
| AC13 | Backend PASS: raw flags retained, noncompetitive XLSX and historical null dates; UI pending. |
| AC14 | Backend error/empty responses covered; loading/retry/error presentation pending in Angular. |
| AC15 | Angular pending: cancellation, stale responses and duplicate export clicks. |
| AC16 | Angular/browser pending: responsive, focus, keyboard and visual continuity. |
| AC17 | Backend PASS: strict query matrix including duplicate and empty params; old-server frontend guard pending. |
| AC18 | PASS: workbook read-back, headers, filenames, literal values, URL preservation and empty workbook. |
| AC19 | PASS: read-only capture; overview 4 queries at 1/100 rows; list/export constant at 1/100, bounded to <=10/<=7. |

No unresolved BLOCKER/MAJOR backend findings in sequential `procollab-review`.
Backend is ready for integration; the complete feature is not accepted until Angular QA.

## Verification evidence

Environment: Python 3.11.15, Django 4.2.11, isolated local PostgreSQL 18,
`DJANGO_SETTINGS_MODULE=procollab.settings_ci`. CI uses PostgreSQL 15; that version
was not run locally. No existing development/production database was used.

Executed regression command (100 tests, PASS, 26.231s):

```text
python manage.py test partner_programs.tests.test_project_case_drilldown partner_programs.tests.test_project_case_analytics partner_programs.tests.test_program_filters partner_programs.tests.test_exports partner_programs.tests.test_program_filter_access partner_programs.tests.test_project_analytics_api partner_programs.tests.test_project_analytics_attention_api --noinput --verbosity 1
```

This covered 12 new and 88 existing tests. Final additional option-removal and
owner/team permission fixtures were verified by:

```text
python manage.py test partner_programs.tests.test_project_case_drilldown --noinput --verbosity 1
```

Final targeted result: **13 tests, PASS, 6.739s**, exit code 0. Combined coverage is
101 distinct tests, not 113: the targeted run repeats the feature tests.

- Checked by source: baseline/diff, permissions, consumers, legacy branches and AC audit.
- Checked by tests: both commands above, PostgreSQL-backed API/workbook/query assertions.
- Checked by static checks: `manage.py check` (0 issues),
  `manage.py makemigrations --check --dry-run` (no changes), flake8 on all six changed
  Python files; Black on five files passed. `exports.py` has one pre-existing Black
  formatting difference in the untouched legacy rates builder, reproduced from HEAD;
  no new formatting differences. `git diff --check` passed.
- Checked by build: no separate backend image/package build run.
- Checked in browser: not run; no frontend implementation in this task.
- Not checked: full backend suite, PostgreSQL 15 CI, deployed SHA/live data,
  production-scale export time/memory, Angular end-to-end and visual/accessibility QA.

## Angular handoff

Implement the approved seven states using the existing AnalyticsDrilldown; no Case
column inside the selected modal, no evaluation metrics and no staff UI gate change.
Q2 requires showing without_case when its project count is positive even if there
are no case definition/options. Search changes list/count only; compact metrics and
export remain full-bucket. Do not pass search or pagination to export.

Backend must deploy first. Validate the new list response contract before enabling
case exports; old servers may ignore query parameters. Preserve response filename,
or align the existing frontend filename helper with the backend scope. Add UI
pagination/search/retry/cancellation tests, all seven visual states, responsive and
keyboard checks. No silent fallback to the legacy all-project list/export.
