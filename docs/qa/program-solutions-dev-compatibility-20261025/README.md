<!-- @format -->

# Совместимость решений с актуальным dev

Статус: **локальные compatibility checks PASS; полный Linux CI и первый выпуск не завершены; не READY TO MERGE**. Существующие Project-программы не переключаются и не удаляются. Исправлен подтвержденный CI конфликт двух веток миграций: исходная nullable certificate0031 взята без изменений из dev, пустая0039 зависит от обеих веток. Исторические migration names/operations сохранены.

Product BE `7cfe01be1c2caba38ad04fef0ab6d68147df1d02`, feature prior `b66cf6cbfbfaadf39753d90d847e7330f79efd9e`, observed dev BE `587a9155b9f53d9e50981a9939a7007c19fd6ecc`. FE `ca1b203a34fddedd6f7d7d6a45752073697dfd7c` не менялся; его observed dev `08414b794dd5b34de5471dddaa19cd0af7f4a167` содержит отдельные certificate changes. Prospective BE tree `2b93d6a99be4a1ac250912b59bea7b220ebf195f` получен git merge-tree/archive без branch merge/rebase/force-push. Его850 Python sources имеют manifest SHA в evidence; source checks не являются full merged runtime regression.

## Проверки

- **439 PostgreSQL tests /429.683s/OK без skips**: все решения и4 legacy publisher tests, включая3 новых migration tests. Затем test-only backend guard/portability исправление: **15 PostgreSQL /51.294s/OK без skips**, все3 observed pg_blocking_pids races и оба порядка миграций выполнены. Focused15 — subset, не прибавлять к439. [Точные targets](native-targets.txt). Wrapper изолирует только Windows file logger sink; домен/DB не мокируются.
- **SQLite15 /51.926s/OK,3 skips**: обе migration orders действительно выполнены; пропущены исключительно3 PostgreSQL lock races. Предыдущий general CI1809 дал ровно3 failures на vendor assertion этих race tests и69 skips; guard согласован с существующими lock suites. PostgreSQL assertions и lock observations сохранены. Это отдельная среда, не полная проверка backend.
- Black5/Flake8/Django check/makemigrations consistency PASS. В [окончательном prospective snapshot](prospective-source-final.json) также check/check models/makemigrations PASS: конфликтов нет, единственный leaf0039, pending main migration plan пуст. Эти проверки read-only; prospective runtime/PDF suite локально не объявляется пройденным.
- [Main forward rehearsal](main-migration-retention.json) применил ровно существующую upstream0031 и пустую0039. Все прежние поля/строки27 моделей совпали до/после: `74555320f955379af8b51b609d5f27e6e6663fd9a2a8756ad871a9a383103ba6`. [Повторное readonly чтение](retention-final.json) после439 подтвердило тот же hash. Main не откатывался/сбрасывался; реальные program flags не менялись. Project4→4; CPUB/C2 snapshots/events и7 старых registration audits включены. В main0 PDF rows; непустые PDF/backfill/token/original rendered_batch доказаны isolated tests обоих порядков.
- C00 **1.21.0/156 schemas/59 operations/305 scenarios** и3 shared files byte-identical BE/FE. Полный contracts folder и исходная QA01 matrix byte-exact относительно предыдущего CPUB checkpoint. API/права/Angular код этой поправкой не менялись; прежние2955 FE tests/types/build относятся к зафиксированному FE, не к еще не собранному latest-dev FE.

## Сохраненные неудачные попытки и ограничения

Expanded native459 завершился access violation `0xC0000005` в WeasyPrint FontConfiguration до итогового результата. Standalone вызов без Django также падает, в том числе с собственными временными Mont fonts. Точная причина native DLL неизвестна. Renderer и его assertions не менялись,459 не объявляются PASS; нужны full certificate/backend tests в поддерживаемом Linux CI конкретного нового HEAD. Raw failed/probe logs сохранены вне Git; их hashes/причины в [evidence](evidence.json).

Предыдущий [PostgreSQL CI40223628921](https://github.com/PROCOLLAB-github/api/actions/runs/40223628921) failed на двух leaf nodes; предыдущий [general CI40223626180](https://github.com/PROCOLLAB-github/api/actions/runs/40223626180) failed на3 SQLite/vendor assertions, Lint success. Failed log general CI получен через gh после Transport closed connector. Новая проверка начнется только после push; ее статус нужно читать по конкретному новому HEAD, старые runs не перезапускались.

[INTEG01–06 spec/audit](../../product/program-solutions-dev-compatibility.md): graph и retention подтверждены; full Linux integration остается открытым. Старый CPUB report сохраняется как evidence своего checkpoint, его найденный graph defect исправлен этой следующей поправкой. Порядок rollout: совместимые models/migrations → upstream0031+empty0039 → backend/workers → frontend. Schema-down после записанной истории запрещен; creation-only rollback сохраняется. Новых merge/deploy/real program switches нет.

Исходные26 AC не менялись:23 PASS, AC18/19 OPEN, AC21 отдельно BE10. D02/D03 approval и draft eligibility уже запрошены. Angular manager/public screens, полный QA01/REL01 и весь первый выпуск остаются в scope. Никакие credentials/JWT/private baseline rows не публикуются.
