# BE08A: административная смена кейса после сдачи

25.10.2026. [Контракт и модель](../../product/program-solutions-be08-case-history.md), [evidence](evidence.json), [HTTP](http-wire.json), [миграция](migration-evidence.json). Выполнен ACH01–ACH08 в описанном scope; полный BE08/QA01/REL01 остается открытым. Исключение участников, удаление регистрации и отвязка/архив заявки — следующие действия, они этим этапом не реализованы.

Backend product91fdbc3f6199d6e0b861caa23063766afd18a385, frontend product74037240c7f10687b24b5627472e5225fb58a381. C001.17.0:131 schemas/51 operations/230 независимых сценариев; три общих файла byte-identical. Из128 прежних схем расширена только SolutionCaseChangePreview;127 прежние,3 новые.6 preview responses получили эффекты, два submitted сценария меняют прежний запрет на согласованное разрешение; всего изменены7 прежних сценариев,210 неизменны,13 новых.

## Подтвержденное поведение

Подписанные case preview/apply доступны организатору своей программы до и после сдачи. Сданный текущий snapshot меняет только кейс; исходный и новый снимки хранятся в SolutionAdministrativeChange. Остальные ответы, форма, состав, капитан, дата сдачи и оценки сохраняются. Снимается только несовместимое назначение без оценок; оцененные назначения сохраняются по прежнему правилу management_project_actions.

История read-only и program/solution/change-scoped. Участник и эксперт получают403, anonymous401, чужой change404, unknown query400. Старый confirmation после другой правки и replay409; обычный captain PATCH остается409/team_frozen. Создание отключено и срок сдачи закрыт, но привилегированная смена кейса и чтение существующей работы/истории доступны. История не раскрывает регистрационные данные или email.

56 настоящих HTTP responses /23 корректных request bodies прошли текущий C00:53 core responses КЧ/хакатона и3 дополнительных legacy boundary checks. В новых программах35/36 созданы и сданы решения51/52 с двумя принятыми участниками. Числовой0 и boolean false ответов сохранены с правильными типами. Значения оценок остаются строками «0»/«False» по действующему протоколу; default текстовый критерий с null не подменяет эти строки.

Две новые ревизии1/2 сохраняют полные before/after snapshots и точный кейс с пробелами/pipe. В каждом решении2 оценки сохранены, из3 назначений удалено только одно неоцененное несовместимое. Настоящие expert frames до/после дают прежние критерии/оценки; снятый эксперт больше не читает эту работу. Подтверждение выполнено по одному разу на программу, история содержит по одной записи.

Дополнительная проверка старой программы34 сохраняет legacy_project4/link3 в context. Попытки solution history/case preview в этом режиме дают409/solution_mode_unavailable и ничего не меняют. Все ранее существовавшие строки22 выбранных доменных моделей совпали с baseline. Новых Project=0;2 новых ProgramSolution,4 принятых членства,2 принятых приглашения,4 исходные оценки и новые назначения относятся только к свежим fixtures. Их setup отделен от проверяемых case actions. Auth/User.last_activity и новые fixture rows не входят в этот hash-инвариант.

## Проверки

- 353 native PostgreSQL solution tests PASS, включая13 новых tests:11 history/integrity и2 наблюдаемых races.32 focused case/history tests — подмножество353, не дополнительные32. Пять case race tests действительно дождались общего program lock по pg_blocking_pids; два новых проверяют submitted confirm×confirm и confirm×score update. Сбой журнала откатывает case/snapshot/version/assignment removal целиком. Изменение значения оценки при том же ID или scope делает прежнее подтверждение устаревшим.
- 148 legacy Project/invite/submit/case tests PASS на том же новом product source в отдельной Unicode test DB. Старые Project handlers и модели не менялись.
- 2862 frontend tests/481 files +strict C00 types, development build, scoped ESLint и locked Prettier3.8.3/2020 source files PASS.49 case/history wire tests включают16 новых history checks. Detail unknown-query сценарий проверен на backend/настоящем HTTP; frontend detail client намеренно не принимает произвольный query.
- Black/Flake8, Django check, migration consistency и C00 validator PASS. Предыдущий backend f9ca4c4 CI завершился success; новый product CI проверяется отдельно и этим предыдущим результатом не подменяется.

Локальная миграция0035 создала только таблицу истории/constraints. До и после применения все прежние22 выбранные модели, включая33 программы,49 решений,4 Project, оценки и файлы, совпали по hash. Новая таблица была пуста. Схема обновлена только в local-procollab_ci и изолированной test DB; dev/production migration/deploy не выполнялись. При rollback нельзя удалять таблицу истории; creation-only flag остается способом остановить новое создание.

## Происхождение и ограничения

Raw: `Z:/Документы/PROCOLLAB-dev/design-artifacts/program-solutions-20261024/qa01-case-revision`. Логи/helper hashes и source refs сохранены в evidence. JWT/credentials не записывались в wire; signed preview proofs в копии для Git заменены строкой redacted. C00 валидировался до этой redaction. Raw local wire сохраняет точные события; публичная копия отличается только удалением proofs.

Прогон продолжался по сохраненным фазам. Первая попытка harness ожидала200 вместо правильного201 создания приглашения; существующее pending приглашение затем прочитано и принято, повторной отправки не было. Следующие ожидания уточнены по реальному score DTO: строки значений и отдельный default comment criterion. Решения/сдача/оценки не пересоздавались и не сбрасывались. Дополнительные3 legacy checks — отдельный read-only verifier, не новый полный case journey.

Первый migration verifier остановился до DDL из-за предположения, что PK каждого выбранного model называется id; исправлен для UserFile с другим PK. Первая test-fixture версия превышала прежнюю quota, использовала неверное имя position и пыталась запрещенным обычным writer очистить template; timestamp assertion исправлен для эквивалентных Z/+00:00. Это сохраненные ошибки fixtures/harness, не скрытые продуктовые PASS. Финальные focused/full suites прошли после исправления этих ожиданий.

Нового Angular UI, нового browser journey или полной visual/a11y/CDN приемки в этом backend/API этапе нет. D02/D03 approvals уже запрошены, вопросы повторно не задаются. Конкурсные несданные черновики, manager/results/public интеграции, остальные административные исключения и полный REL01 остаются открытыми. Старые программы не переключались и не переносились, merge/deploy нет.
