# BE08: подтвержденная смена кейса черновика

До реализации проверены legacy management_project_actions.inspect_action/apply_action, validate_case_value и serializer. Смена кейса относится к одной заявке, доступна organizer/admin своей программы, требует точного актуального варианта и signed preview/confirm. Материалы проекта и оценки не переписываются этим действием; несовместимые неоцененные назначения снимаются отдельно в старой ветке.

Новая ветка переносит смену кейса несданного ProgramSolution. Текущий инвариант immutable submitted остается в силе до ответа на уже заданный вопрос об административных исключениях. Это не решение навсегда запретить такие исключения и не завершение полного BE08. Удаление/отвязка не реализуются: legacy сохранял исходный Project, а новое решение само владеет материалами; текущий вопрос о хранении/сданных работах не подменяется cascade delete. Нового Angular UI нет; он зависит от D02 approval.

## Контракт до реализации

C00 1.15.0 добавляет два POST `/programs/{program_id}/management/solutions/{solution_id}/case/preview/` и `/case/apply/`. В request точный case_name (1–1000 символов, не только пробелы); apply дополнительно preview_token. Unknown fields/query и unsafe IDs отклоняются. Старый submit action API и все прежние 125 schemas/47 operations/185 scenarios сохраняются без изменения.

Preview возвращает настоящий SolutionRef, case_field_id, current_case (nullable), целевой case_name, solution_version, Issue[], can_apply и nullable token. Проверяются mode/manager scope/текущая форма/вариант. Тот же кейс, submitted или неожиданное наличие оценок/назначений дают can_apply=false с объяснением и token=null. Preview не пишет domain data. Неконкурсный draft поддерживается: выбор кейса не требует искусственной сдачи. Creation flag/deadline не отключают действие над существующей заявкой.

Apply привязан подписью на 10 минут к actor/program/solution/целевому кейсу и сохраненному состоянию. Program→solution→fields/answers/members locks и повторная проверка защищают от lost update. Fingerprint включает текущую форму, версию/капитана/название/status/snapshot/published_at, ответы/состав и наличие оценок/назначений. Чужой/истекший/устаревший token и replay дают409 solution_action_conflict; submitted сохраняет409 team_frozen. Изменяется только case answer и версия/updated_at решения; остальные ответы, участники, snapshot, оценки и назначения не удаляются. Непредвиденные evaluation records у draft блокируют команду. Ответ — существующий MutationReceipt.

400 — invalid payload/case, 401 anonymous, 403 manager scope, 404 foreign/missing solution, 409 mode/unconfigured form/token/state/frozen. Все ответы private/no-store. Новых моделей/миграций нет. Прежние legacy handlers не меняются.

## Приемка

| AC | Ожидаемый результат |
| --- | --- |
| CASE01 | Organizer/admin только своей программы; participant/expert/foreign IDs/legacy/unsafe input закрыты, private/no-store |
| CASE02 | Preview read-only, правильные SolutionRef/current/target/version/field; null token для same/submitted/unexpected evaluation |
| CASE03 | Exact options включая пробелы/символ pipe, смена null→case и case→case; только case answer/version/time изменены, 0/false и состав сохранены |
| CASE04 | Token actor/program/solution/case/expiry/signature/state и replay проверяются; изменение формы/ответов/состава/status не теряется |
| CASE05 | Submitted snapshot/score/assignments не меняются; normal captain deadline/rights и прежние action paths сохранены |
| CASE06 | Два confirm, confirm×captain PATCH и confirm×submit реально ждут program lock; один допустимый исход без lost update/двойной версии/изменения frozen snapshot |
| CASE07 | C00 additive/independent examples, generated frontend types/port/repository/adapter/use cases и реальные interceptor wire tests согласованы |
| CASE08 | PostgreSQL regression, настоящий HTTP КЧ/хакатона/noncompetitive, audit существующих данных и source review подтверждают scope |

Порядок: spec/C00 → backend/service/API → PostgreSQL verification → frontend API layer → real HTTP → review → draft PR. Полный QA01/REL01 и BE10 этим блоком не закрываются.

## Результат

CASE01–CASE08 PASS в API scope; [evidence, точные refs/hashes и границы](../qa/program-solutions-case-actions-20261025/README.md). C001.15 содержит128/49/209 при неизменных прежних125/47/185. Read-only preview, signed state и single-field write реализованы отдельным service/API; старый submit action не расширялся.19 новых PostgreSQL tests включают три наблюдаемых program-lock races и настоящие frozen score/assignment records. Broad356 PASS до последнего token-type guard; final52 после него и добавления submit race PASS. Actual115 C00 responses/88 valid JSON requests и15 rejected invalid requests трех форматов, no domain writes verifier; frontend2827/480+strict types/build/lint PASS. Full feature/manager UI/post-submission policy и CI нового commit отдельно не объявляются завершенными.
