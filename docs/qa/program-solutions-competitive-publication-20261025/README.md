<!-- @format -->

# CPUB: опубликованные материалы сданных КЧ/хакатон решений

Статус: **CPUB API PASS; первый выпуск не завершен, не READY TO MERGE**. Данные живут в ProgramSolution/answers/team/UserFile; Project не создается. После окончания solution-программы и при publication flag publisher отмечает активные submitted работы. Неконкурсные saved материалы по-прежнему без искусственной сдачи. Eligibility несданных конкурсных черновиков уже запрошена и остается открытой.

Product refs: backend `8d089229617893745c5dfa749f20d891152b9caa`, frontend `609253594c88fc8255e4841c918fc375a72e47e5`. Новых DB migrations в CPUB нет. Публичные DTO/permissions на запись не расширялись: два прежних GET возвращают allowlist по marker, конкурсные draft/архив/неопубликованные скрыты. Уже установленный marker не снимается выключением флага или переносом даты; confirmed archive скрывает выдачу, сохраняя данные.

## Контракт и потребители

C00 **1.21.0 / 156 schemas / 59 operations / 305 scenarios**. Все156 схем и структура59 операций неизменны; изменились описания двух public GET. Добавлены6 сценариев. **Один временный пример** `published_solution_list_competitive_pending_rule` намеренно меняет404→200 пустого списка: вопрос о draft больше не закрывает весь конкурсный reader. Остальные298 старых сценариев сохранены. Три shared файла byte-identical. Generated TS types отличаются version comment, fixtures отражают новые/обновленный примеры; существующий adapter/repository/use cases принимают тот же DTO.

## Проверки

- Final **432 PostgreSQL tests/OK без skips**, включая12 новых CPUB tests и3 observed lock races. Native wrapper использует `test_procollab_ci_archived_rating_unicode` (ICU ru-RU), keepdb, обычный manage.py test mode; патч изолирует только файловый logger sink Windows, не домен/БД. [Точные targets](native-targets.txt). Отдельно **4 legacy Project publisher tests/OK**; focused30 — subset, не складывать с432.
- **2955 FE tests / 484 files**, strict types, development build, scoped ESLint PASS.31 public wire tests — subset. Black/Flake8/Django check/migration consistency/C00 PASS. Build имеет прежние Sass warnings. Locked Prettier3.8.3 до новых reports:2061 files PASS; итог с reports:2068 files PASS.
- **97 немокированных HTTP ответов / 34 валидных тела**, C00 validation до редактирования Git wire. Новые программы49/50/51, решения66–71. КЧ/хакатон: create/save/invite/accept/pending/submit/rate → controlled finish/flag → scoped publisher → anonymous list/search/detail → signed case/member revision → public applied snapshot → archive → public404. Noncompetitive: saved work +пустая saved work опубликованы без submit, pagination проверена. Before finish/flagFalse publisher0, затем1/1/2, repeat0; creationFalse сохраняет чтение/админ действия. Program flags изменялись только у собственных fixtures с проверенным prefix, global main publisher не запускался.
- **25 прежних моделей** (включая Auth User, Project и C2 audit/history) совпали до/после и после final native/FE/build checks: SHA `54631ba6896d1d18cadf7f855ca1fd1b83b0a2396a72b28e2b61b720f1783169`. **Project4→4**, все7 прежних registration audit headers сохранены. У49/50 marker/архивный snapshot и4 criterion values (0/False/комментарии) сохранены, у51 нет искусственной сдачи. Creation flags трех fixturesFalse.
- Owned API wrapper10408/child39748 остановлены,8877 освобожден. Старые8769/8871/8876/55439 не менялись. Старые8871/8876 не использовались как актуальная сборка.

[Evidence/source hashes](evidence.json), [contract compatibility](contract-compatibility.json), [HTTP wire](http-wire.json), [domain proof](domain-and-contract-evidence.json), [final readonly retention](retention-final.json).

## Неудачные и промежуточные попытки

До реализации3 проверки дали3 product FAIL: publisher0 вместо1 и competitive404. Первый focused30 дал2 fixture errors: вариант нового кейса не был добавлен в конфигурацию, а secret text был передан в int criterion. Fixtures исправлены на валидный кейс/str criterion, валидаторы и guards не ослаблялись. После30/OK и431/OK тесты усилены новым обязательным полем и pagination/foreign scope; final432/OK. Старые logs/failed attempts сохранены с hashes в evidence. Первый verifier исходных AC включил header в счетчик; после точного выбора все26 строк byte-exact. Fixtures/критерии/оценки ради PASS не сбрасывались, завершенный HTTP helper запрещает replay.

JWT/credentials не входят в report. **12 signed proof occurrences скрыты только в Git-копии wire** после проверки настоящих запросов/ответов. Raw private manifest/wire и helper logs находятся в TEMP/design-artifacts; не переносить их в Git. Повторять завершенный HTTP script нельзя:66/68 уже в архиве. Допустим отдельный readonly verifier.

## Integration finding и границы готовности

[Read-only prospective dev graph](prospective-dev-integration.json): target BE587a9155/FE08414b79 продвинулся certificate changes. Git merge-tree preview до CPUB не имеет текстовых конфликтов, но новый dev `0031_programcertificate_rendered_batch` и feature `0038_solution_registration_removal_audit` дают **две leaf nodes**. Текущий checkout graph чист. Overlay MigrationLoader(None) не пишет в БД; migration/sync/merge/rebase/force-push не выполнялись. **MAJOR required_next**: совместить certificate models/migrations и повторить граф/retention verification без перенумерации или удаления старых миграций.432/2955 не доказывают еще не собранную объединенную версию.

Не проверены новый Angular public UI, CDN bytes (собственные metadata fixtures), production и окончательная draft eligibility. D02/D03 уже ожидают approval; новый UI не реализован этим checkpoint. Исходные26 AC сохранены:23 PASS, AC18/19 OPEN, AC21 отдельно BE10. Полный QA01/REL01, интеграция последнего dev и весь первый выпуск остаются в scope. Старые programs автоматически не переносятся; новых merge/deploy/реальных switches нет. После первого конкурсного marker сохраняется reader/publisher1.21: старый competitive404 reader скроет опубликованные материалы при откате.

[CPUB spec и audit](../../product/program-solutions-competitive-publication.md).
