# QA01: подтвержденная смена кейса решения

Реализован API существующего организаторского сценария для несданного решения: preview → подписанное подтверждение → точная смена case answer. Материалы, состав и сданные snapshot сохраняются. [Требования CASE01–CASE08](../../product/program-solutions-be08-case-actions.md). Это API часть BE08/FE08, не готовность всего первого выпуска или нового manager UI.

C00 1.15.0:128 schemas/49 operations/209 independent scenarios. Все прежние125/47/185 структурно сохранены, включая submit action enum и ошибки. Три contract файла byte-identical; [compatibility](contract-compatibility.json). Frontend generated DTO/port/repository/adapter/2 use cases и31 новых wire tests с настоящим CamelcaseInterceptor; strict types запрещают missing token и Project references.

| AC | Evidence и результат |
| --- | --- |
| CASE01 | API tests manager/staff/captain/member/expert/foreign manager/foreign IDs/anonymous/mode/input; actual HTTP401/403 и private/no-store. Unsafe IDs, unknown body/query, non-string case/token отклонены. |
| CASE02 | Read-only preview hash, SolutionRef/field/current/target/version; same/submitted/unexpected score или assignment дают can_apply=false/token=null. |
| CASE03 | Actual КЧ/хакатон/noncompetitive: case→case и null→case, точные leading/trailing spaces и pipe. Меняются case answer/version/time; 0/false, name/captain, accepted roster и pending invitation неизменны. |
| CASE04 | Signature/expiry/actor/solution/target/state и replay проверены tests; изменения answer/member/form/name без version bump вызывают conflict. Реальный captain PATCH делает старый token неприменимым. Program scope проверяется foreign IDs и decoded proof context. |
| CASE05 | Frozen preview/apply не меняют submitted snapshot и настоящие score/assignment records в tests; два actual submitted anchors сохранены. Непредвиденные draft evaluation records не удаляются. Noncompetitive и creation=False/closed deadline поддерживают существующий draft case action. |
| CASE06 | Три PostgreSQL races: confirm×confirm, confirm×captain PATCH, confirm×submit. Оба worker реально ожидают program row lock по pg_blocking_pids до снятия контроллера. Одна ordered version; frozen snapshot не меняется. |
| CASE07 |31 wire tests покрывают все24 новых независимых сценария, safe ID bounds, exact strings и opaque token; вместе с прежними30 submit tests61 PASS. Final frontend2827/480+strict types/build/scoped lint PASS. |
| CASE08 | [82 первичных HTTP responses](http-evidence.json) и [33 post-review requests](domain-and-contract-evidence.json), все115 responses проверены C00;88 schema-valid JSON requests,15 намеренно неверных типов отклонены400. Прежние строки15 выбранных domain моделей/Project неизменны; verifier не пишет domain data. |

Все CASE gates PASS в описанном API scope. Broad local PostgreSQL regression:356 tests, включая все solution modules/оценивание и прежние management actions/removal/services, PASS. После финального строгого string-token guard и добавления submit race выполнены52 tests:19 новых case tests и прежние submit/legacy actions, PASS. Не записывать356 как повторенный прогон после последней правки. Black/Flake8, Django check, migration consistency/C00 PASS; новых migrations нет. Новый commit проходит собственный CI после push; зеленый ad3945e относится к предыдущему source.

## Среда и происхождение

Новые synthetic программы30/31/32, решения45/47/49 и anchors46/48/50, prefix qa01c-20261025-2b16a5aa. API8877, PostgreSQL18/main procollab_ci, locmem mail. Backend поверх ad3945e, frontend поверх37ecd71d; runtime source hashes в [manifest](local-artifacts.json). Test DB отдельный test_procollab_ci_unicode. Ни реальные программы, ни production не переключались. Пароли/JWT/подписанные токены не включены в Git; raw wire хранится локально под SHA256.

Первичный HTTP сценарий выполнил все положительные case writes до последнего type-only guard токена. Service logic осталась byte-identical. API перезапущен;33 current-source requests проверили отказ числовым/boolean/object/list токенам, валидный string-token путь до bound-state проверки, права/private headers и неизменные конечные данные. Этот verifier не повторял case writes и не сбрасывал fixtures. Оба этапа сохранены отдельно.

Первые локальные test attempts исправили предположения fixture: второго варианта кейса еще не было, экземпляр solution имел старую version, authentication error использует authentication_required. Это не продуктовые ошибки и не основание сбрасывать main fixtures. При source review усилена проверка string-token и добавлено настоящее score/assignment сохранение и confirm×submit race.

Финально три primary решения остаются drafts с точным новым кейсом,0/false, одним капитаном и одним pending; creation flags=False. Anchors46/48 submitted со старым snapshot,50 остается draft. Прежняя baseline выборка15 моделей сохранена. Current-source verifier не менял домен; auth/session/last_activity не входят в этот hash audit.

D02/D03, административные исключения уже сданных работ, удаление/отвязка с сохранением материалов, конкурсная публикация и полный QA01/REL01 остаются открытыми. Никакой permanent draft-only замены требуемой политики не утверждалось. Новый Angular screen/route/control/SCSS не добавлялся. Merge/deploy и BE10 не выполнялись.
