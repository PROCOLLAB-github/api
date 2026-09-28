# Review backend после переноса на dev

Дата: 28.09.2026. Skill: procollab-review. **READY FOR ANGULAR**.

Сравнение: origin/dev `29be99d` → ветка `feature/dev-analytics-case-drilldown-backend`.
Исходный implementation сохранён commit `608bf09` в первоначальной ветке;
перенос от dev — commit `0ad79b3`. История master в dev не переносилась.
Deployed SHA не подтверждался.

Повторно проверены specification/AC01–AC19, Q1–Q4, [API contract](../analytics-case-drilldown-api.md),
полный diff, модели, permissions, существующие dev analytics/filter/export consumers и тесты.
Общий classifier теперь находится в существующем dev `services/case_analytics.py`;
сохраняется `build_case_analytics` и dev endpoint `manager-overview`.
List и export расширены opt-in ветками; остальной views diff — необходимые imports.
Новых моделей, endpoints, permissions, migration или frontend changes нет.

## Findings

BLOCKER / MAJOR / MINOR после повторной проверки не обнаружены.

NOTE из предыдущего review частично устранён: заголовки нового XLSX теперь проверяются
literal списком из specification, без импорта константы exporter.
Legacy export дополнительно сравнивается с прежним builder; независимые существующие
`test_exports` проверяют legacy контракт. Это не объявлено новой полной приёмкой Angular.

## Фактически выполнено

- 187 feature/regression tests на отдельном PostgreSQL 18 ICU und — PASS, 45.647 s;
  точная команда из девяти test modules приведена в API contract.
- После усиления workbook assertions: `test_project_case_drilldown` — 13 PASS, 6.681 s.
  Это повторные тесты, не ещё 13 уникальных сценариев.
- flake8 шести изменённых Python-файлов — PASS.
- `manage.py check` — 0 issues.
- `manage.py makemigrations --check --dry-run` — No changes detected.
- `git diff --check` — PASS после удаления лишней пустой строки документа.
- Query capture: overview 4 SQL; list/export одинаковое число запросов на 1/100 строках,
  <=10 / <=7; сериализатор 100 строк — 0 дополнительных SQL, writes отсутствуют.

Первый regression-прогон на collation C дал ошибки существующего кириллического поиска;
повтор на Unicode collation прошёл. Код поиска ради локальной среды не изменён.

## AC и ограничения

Backend evidence подтверждено повторным прогоном для AC02–09, AC10 (server search/page),
AC11–13, AC14 (ответы/ошибки), AC17–19. Полные AC01, AC15, AC16 и UI-части остальных
требуют Angular/browser evidence в связанном PR; старый backend-only audit не подменяет его.
Staff API-доступ сохранён, расширение Angular gate не разрешено.

Локально не запускались полный backend suite, PostgreSQL 15 CI и image build.
Не проверялись live data/production SHA и production-scale время/память XLSX.
GitHub CI после публикации PR фиксируется отдельно.
Merge/deploy не выполнялись; порядок — backend → проверка dev API → Angular.
