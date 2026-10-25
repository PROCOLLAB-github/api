# Совместимость решений с актуальным dev: граф миграций

CI40223628921 на b66cf6cb остановился на Check migration consistency: dev добавил `0031_programcertificate_rendered_batch`, а feature продолжает ветку `0031_solution_field_options` → `0038_solution_registration_removal_audit` от общей `0030_program_solution_foundation`. Git merge-tree не имеет текстовых конфликтов, но Django обнаруживает две leaf nodes. Это подтвержденный integration defect полного выпуска, не ошибка CPUB queryset.

Минимальное исправление: взять без изменений уже существующие в observed dev587a9155 nullable `ProgramCertificate.rendered_batch` и его migration0031, затем добавить пустую merge migration0039 с зависимостями от обеих веток. Исторические migration names/operations не менять, старые таблицы/решения/Project/материалы/оценки/историю не удалять. Certificate services/UI не переписываются; их изменения последнего dev проверяются в отдельном prospective integration snapshot. Код/PR ветки не сливаются и не переписывают историю.

В CPUB контракте ничего не меняется: C00 1.21.0/156 schemas/59 operations/305 scenarios, решения продолжают отдельную модель. Порядок будущего rollout: совместимые models/migration graph → additive upstream0031 и empty0039 → backend/workers → frontend. Schema-down после записанной истории недопустим, creation-only rollback сохраняется. Реальные программы не переключаются; rehearsal допустим только в guarded localhost PostgreSQL CI окружении.

| AC | Требуемое доказательство |
| --- | --- |
| INTEG01 | Один leaf и detect_conflicts={} в текущем/prospective графе; исходная dev0031 byte-exact после нормализации line endings, merge0039 без operations |
| INTEG02 | Solution-first0038 →0039 сохраняет legacy Project, draft/submitted/архивные JSON, ответы/состав/оценки; certificate pdf bytes/metadata не меняются, новый FK backfill соответствует прежнему batch |
| INTEG03 | Certificate-first0031 →0039 сохраняет PDF bytes, download token и уже записанный rendered_batch; существующие base solutions/Project не теряются |
| INTEG04 | Текущие solution/certificate/legacy tests и prospective merged source migration checks подтверждают совместимость наблюдаемого dev; не подменять prospective proof текущим checkout |
| INTEG05 | Guarded local forward migration/recheck сохраняет все выбранные прежние rows/колонки и реальные CPUB/C2 snapshots/events; main не сбрасывается, старые миграции не откатываются |
| INTEG06 | C00/FE consumers и исходные26 AC не меняются; Linux CI конкретного нового HEAD проверяется отдельно, общий QA01/REL01/D02/D03 не закрывается автоматически |

Проверка должна различать current feature refs, observed dev refs и prospective tree/source hashes. Снимок prospective кода нужен только для проверки: он не выполняет merge/rebase/force-push/deploy. Никаких новых продуктовых правил сертификатов не вводится.

## Аудит реализации 2026-10-25

Скопированы ровно nullable FK и исходная dev0031; generated merge0039 не содержит операций. Три новых PostgreSQL теста прошли отдельно (48.751s), затем вместе со всей регрессией решений и четырьмя legacy publisher tests: **439/OK, 429.683s, без skips**. Тесты меняют схему только isolated test DB, проверяют оба порядка веток и восстанавливают последний граф. Значения JSON 0/False, архивы/история/оценки и PDF bytes/download token сохраняются; certificate-first сохраняет первоначальный rendered_batch, даже если текущий batch другой.

Guarded localhost main rehearsal применил только две forward migrations. Все прежние колонки/строки **27 моделей** совпали до/после: SHA256 `74555320f955379af8b51b609d5f27e6e6663fd9a2a8756ad871a9a383103ba6`. Main не откатывался/сбрасывался, реальные program flags не менялись. В main нет PDF rows; непустой certificate backfill подтвержден двумя isolated migration tests. Black/Flake8/Django check/makemigrations consistency прошли.

Расширенная локальная попытка на459 tests не завершилась: native Windows access violation `0xC0000005` внутри WeasyPrint FontConfiguration. Отдельный вызов FontConfiguration без Django воспроизвел сбой, включая собственную временную конфигурацию с Mont fonts. Точная причина DLL не установлена. Renderer/tests/условия не менялись; 459 не объявляются PASS. Полный PDF/backend suite должен пройти в поддерживаемом Linux CI на конкретном новом HEAD. Старый general CI40223626180 завершился failure в Run tests (Lint success); получение его logs через connector дало Transport closed, причину не подменять известным migration failure отдельного PostgreSQL CI40223628921.

INTEG01–03/05 подтверждены для текущего checkout; INTEG04/06 остаются частичными до проверки prospective исходников и Linux CI. Полный выпуск, D02/D03, исходные AC18/19 и отдельный BE10 не закрыты этим исправлением.
