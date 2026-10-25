<!-- @format -->

# QA01: архивирование решения во время оценки

25 октября 2026 года. Сервер явно запрещает оценивание архивной работы до проверки критериев/квоты/назначения. Это исправление поведения внутри согласованного D01, а не завершение первого выпуска.

Триггер: эксперт одновременно организатор своей программы, открыл оценку; работа архивирована до подтверждения. До исправления сервер возвращал max_rates_reached/409 в открытом режиме либо not_assigned/403 в распределенном, а явный solution_archived оставлял старую форму на фронте. Теперь POST дает solution_archived/409; материалы, оценочные controls и предыдущий ввод исчезают. Эксперт без сохраненного доступа по-прежнему получает404. Сохраненные значения не переписываются.

Product [BE 394bf166](https://github.com/PROCOLLAB-github/api/commit/394bf1666825ea87e7985b88c401a4e3c9f8d316) / [FE b4191a8b](https://github.com/PROCOLLAB-github/procollab/commit/b4191a8b082e41b318c67c7605fa2764b647c46c). C00 1.20.1:156 схем/59 операций/299 независимых сценариев; все156 прежних схем/59 операций/297 сценариев неизменны, добавлены2 примера. Три shared файла byte-identical. Миграций нет.

## Доказательства

- До fix: native3 —2 FAIL/1 PASS; component10 —1 FAIL/9 PASS. После:420 native PostgreSQL tests/OK без skips,2949 frontend tests/484 files +strict types, development build, scoped ESLint, Black/Flake8/Django check/migration consistency/C00/diff PASS. Focused component/wire21 — subset, не добавлять к2949. Locked Prettier3.8.3 до report:2042 файлов PASS; итог с report:2047 файлов PASS.
- Настоящий Chrome 156.0.8078.47/login, обе формы в одном завершенном запуске: КЧ47 с распределением и хакатон48 с открытым оцениванием, работы64/65.0/False/сохраненные комментарии → локальная2/новый комментарий → вкладка команды сохраняет ввод → подтверждение → archive preview/apply настоящим API → rating POST409/solution_archived → старые поля/форма/команда/ввод убраны → retry GET404. Активные собственные pending/completed counters0/0. Проверены390/1440 без horizontal overflow;8 screenshots,2 просмотрены. Network responses не подменялись; page errors в завершенном запуске0.
-36 ответов/20 JSON bodies проверены C00:18 seed +12 browser +6 readonly verifier. Второй эксперт GET/POST404, капитан читает архив readonly. По каждой работе сохранены все4 ID/value пары (0,False,непустой и системный пустой комментарий), полные hashes scores/answers/members и submission snapshot; попытка записать2 не сохранилась. Назначения сняты только явным архивом. Flags новых программ=False, новые Project не создавались.
-25 прежних моделей, включая Auth User и все записи BE08C2, совпали с baseline `c8196d411a2bbab6838167141baa1ae2b2229df7191f29d97f0d37f66cc56989`. Все7 независимых audit headers и прежние6 C2 events сохранены. Отдельный post-recovery check подтвердил прежний hash23 моделей717c9a66… и состояние C2 до новых fixtures. Новый UI организатора/навигация архива этим checkpoint не добавлялись.

[Browser checks](browser-checks.json), [domain/C00](domain-and-contract-evidence.json), [wire](http-wire.json), [refs/source/raw hashes](evidence.json). Signed proof4 occurrences скрыты только в Git wire после проверки; JWT/Authorization/password не записывались. Private credentials/manifest находятся в TEMP, в Git не включены.

## Сохраненные ограничения и попытки

Первый полный native420 прерван локальными I/O ошибками: postgres перешел в recovery,77 errors. Это не PASS. Также Python не прочитал charmap.py, а первый build copy получил UNKNOWN при чтении chunk. PostgreSQL восстановился самостоятельно, без ручного перезапуска или сброса main DB. После восстановления проверены hashes/все прежние C2 данные. Причина I/O не установлена. Упавшая test_procollab_ci_unicode сохранена; итоговые420 прошли отдельно в новой test_procollab_ci_archived_rating_unicode (ICU ru-RU), без параллельного тяжелого FE прогона. FE2949 завершился успешно.

Focused65 после guard выявил неверный формат тестовой stale revision; input заменен на валидный64-character hash, проверка archive409 сохранена. Первый fixture setup был атомарно отменен валидатором кейса без show_filter, затем helper исправлен без ослабления product validation. Первая попытка запуска браузера не нашла cached executable и не открыла страницу; итоговый запуск использует установленный Chrome. Readonly verifier сначала ожидал3 оценки, затем сравнен с реальным frame: сохранены все4, включая штатный пустой комментарий. Критерии/оценки/работы ради PASS не сбрасывались. Raw failures/logs/helpers и частичная первая build copy сохранены локально.

Raw: `Z:/Документы/PROCOLLAB-dev/design-artifacts/program-solutions-20261024/qa01-archived-rating`. Build copy меняет только API/WS origins одного generated chunk; source environments не менялись. Remote avatars блокировались: screenshots могут содержать broken avatar. Полные desktop/a11y/zoom/production CDN/binary-file сценарии не заявляются. Owned API8877/SPA8882 остановлены, прежние8769/8871/8876 не перезапускались. Seed/browser helpers повторно не запускать: новые работы уже архивны. Readonly verifier можно использовать для сверки, не выдавая повтор за новый путь.

Original26 AC strings сохранены;23 PASS — AC01–17/20/22–26, AC18/19 OPEN, AC21 отдельно BE10. Общий expert/results/public path AC18 еще не доказан. D02/D03 approval, manager/reminder/actions/results/public screens, confirmation/history/archive navigation, competitive unsent drafts и полный QA01/REL01 остаются в первом выпуске. Новых merge/deploy/реальных переключений/BE10 не было.

Preceding C2 f22ea47: Linux PG40212381737 completed/success,39 locking +1818 full/OK без skips; его General40212377825 еще in_progress при упаковке. Preceding C1 bf5fc5a General40208630839 terminal success,1768/OK(skipped67). Это отдельные результаты предыдущих refs. Новый HEAD Linux CI фиксируется после push; PASS ему этим отчетом не присваивается.
