# REL01: создание отдельно от доступа к существующим решениям

Технический scope ROL01–ROL10 PASS; **полный QA01/REL01 и новая сущность еще не завершены**. [Spec, before/after, rollout и audit](../../product/program-solutions-rel01.md).

## Источник и среда

Backend feature поверх 40ba5a7; frontend поверх e57fb04e, C00 1.13.0. Local PostgreSQL 18/main procollab_ci, API 8871, SPA 8875, locmem mail/local file storage. Тесты используют отдельный test_procollab_ci_unicode. Реальные программы/production не включались, merge/deploy не выполнялись.

Миграция добавила False всем прежним программам без смены mode или данных. Rehearsal создал только новые synthetic программы 9/10, переиспользовал пять прежних synthetic аккаунтов. Submitted решения 8/10 и re-enabled drafts 9/11 сохранены; final creation flags False. Пароли/JWT/fixture credential manifest в Git не включены.

## Evidence

- [contract-compatibility.json](contract-compatibility.json): 120 схем/45 операций/161 независимый сценарий. Все прежние 158 сценариев, схемы, request/response schemas, параметры и прежние примеры совпадают с базой; три общих C00 файла byte-identical в двух repos. Type model отличается только header версии.
- [migration-evidence.json](migration-evidence.json): actual 0033→0034, 8 прежних программ и все перечисленные доменные строки/columns сохранены, flags=False. Это не перенос BE10.
- [browser-evidence.json](browser-evidence.json): off на direct new route и program entry → реальный HTTP deny → scoped CLI enable → create → disable → нормальный participant journey → submit/frozen → re-enable/new draft → disable. Обе формы, Mont, JS errors=[], 37 mutating HTTP requests, включая ожидаемые 409. Это не число persisted writes и не zero writes.
- [domain-evidence.json](domain-evidence.json): 30 HTTP checks с C00 validation, currentApplication/repeat/read/permissions/forbidden/disabled/повторная сдача и actual database snapshots; 0 domain mutations этого verifier. PDF download bytes/MIME/owner/597 bytes/SHA-256 подтверждены. Исходная выборка migration baseline восстановлена исключением только новых rehearsal строк/файлов, ее полный SHA-256 совпал: прежние программы/решения/ответы/команда/приглашения/оценки/назначения/files/Project не изменились.
- [run-state.json](run-state.json): проверенные фазы/IDs и rollbackVerified, без сброса submitted fixtures.
- [build-provenance.json](build-provenance.json): только origins одного generated chunk изменены в копии готового development build; хеши исходных frontend files и JS до/после. Source environments/обычный build не патчились.
- [local-artifacts.json](local-artifacts.json): хеши 16 screenshots, шести harness sources в Temp и final backend sources. Browser предшествовал последнему model.save guard fix; после него прошли 261 regression tests и 30 HTTP checks на перезапущенном API. UI/creation gate не менялись после browser прохода.

## Проверки и review

`partner_programs/tests/test_solution_creation_switch.py`: 17 новых tests. Проверяется сохранение реальных доменных значений/права, а не только наличие guard. Два PostgreSQL concurrency tests дожидаются фактического pg_blocking_pids для program lock. Migration test сохраняет submitted snapshot/answers/team и старые columns, восстанавливает latest migration graph. CLI preview/apply/idempotency/unknown/unsafe/legacy enable и stale save в обоих направлениях подтверждены. Existing writers, expert rate/manager results и noncompetitive public publisher проверены при False.

Final backend regression: 261 tests, включая новые 17, все test_solution* + legacy services + solution evaluation + chat permissions/Swagger. Лог C:/Users/evsee/AppData/Local/Temp/procollab-solution-creation-regression.log. Black/Flake8/check/migration consistency/C00 PASS. Frontend: 55 focused (6 новых), полный 2760/478 + strict types, development build, scoped ESLint и locked Prettier 3.8.3/1969 files PASS. Логи procollab-solution-creation-fe-* в Temp. Полный Linux CI этого runtime запускается после push и не подменяется предшествующим зеленым 1724bca.

Review исправил единственный найденный риск: generic save устаревшей карточки мог отменить операторский disable/enable. Теперь существующий program lock перечитывает и сохраняет служебный flag, если update_fields явно его не выбирает; регрессионный test и общий прогон выполнены после fix. Остальные продуктовые права/сроки/snapshot/контракты не менялись.

Визуально просмотрены paused direct route КЧ и existing program-entry modal хакатона. Основной browser путь 390 px; состояния team/materials/readonly проверены на 320/390/768/1440, desktop материалы отдельно. Полные desktop/a11y/zoom, production CDN/рассылки не заявляются. Внешняя сеть блокировалась, default avatars отсутствуют в screenshots. D02/D03 и спорные административные/конкурсные правила этим checkpoint не согласуются и не реализуются.
