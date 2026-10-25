# REL01: отдельное отключение нового создания

Scope этого этапа — технический пункт REL01 о rollout/rollback; весь выпуск остается зависимым от QA01. Source: [каноническое ТЗ](https://chatgpt.com/space/page_9632e9ed74588191b6b3e4b397d55175), REL01 a5436282-a8ed-4c7b-bb51-00cde8bd12ef/e00bad1b-3374-4a2d-8266-57afb7be70b2. Сначала требования/контракт, затем implementation/verification/review. Исходный runtime BE 1724bca, FE e57fb04e; текущий docs-only BE HEAD 40ba5a7.

## Current behavior

`solution_api.context_data/create_solution` проверяют storage mode, текущую заявку, регистрацию/manager exception, срок и конфигурацию формы. `create_solution` держит program row lock; повтор капитана возвращает существующее решение до проверки срока. Отдельного creation switch нет. `solution_team.require_mutable` проверяет storage mode для всех обычных writers: возврат к legacy_project блокирует редактирование/приглашения/сдачу существующих решений и не выполняет требование creation-only rollback.

Два Angular потребителя (`ProgramSolutionComponent`, `DetailProgramInfoService`) сначала открывают currentApplication, затем используют canCreate; blockedReason — открытый string/null. При отказе создания сейчас показывается общий текст о регистрации/сроках. DTO существующей страницы программы перечислены явно; параметры запуска не принимаются management settings API. Legacy API и независимый nextgen контур не используют ProgramSolution creation.

## Target, роли и техническое решение

Добавить `PartnerProgram.solution_creation_enabled: bool`, default=False. Выбор program-scoped persisted флага — технический способ выполнить уже заданное требование отдельного пилота/отката, без нового продуктового правила. Миграция оставляет все прежние программы с False, сохраняя storage mode, решения/ответы/команду/приглашения/оценки/публикацию. Никаких реальных программ при разработке не включать.

Флаг изменяется только оператором через явную scoped management command `set_solution_creation --program-id ID --enable|--disable`; по умолчанию команда делает preview, запись только с `--apply`. Она блокирует одну строку программы, не переключает storage mode и не меняет другие данные. Unknown/unsafe ID и попытка enable legacy_project отклоняются. Текущие REST permissions не расширяются; клиент не передает флаг. Новый пользовательский экран/контрол не нужен; меняется только текст существующего отказа, дизайн D00 сохраняется.

С выключенным флагом запрещено только создание новой заявки. Капитан по повторному POST получает существующую с 200; accepted member сохраняет прежний 409/already_in_program_team. Чтение, список, формы, файлы, приглашения, принятие в существующую команду, редактирование и сдача существующих работ сохраняют прежние права/сроки/frozen guards. Неконкурсная публикация и эксперт/manager API не проверяют этот флаг.

## C00 1.13.0 before/after

- GET `/programs/{program_id}/solution-context/`: прежний Context, без нового обязательного поля. При отсутствии текущей заявки в solution mode у зарегистрированного участника/manager с выключенным флагом can_create=False, blocked_reason=solution_creation_disabled. Порядок: current application → mode → права → creation flag → срок → форма. Existing currentApplication имеет прежний приоритет.
- POST `/programs/{program_id}/solutions/`: прежний payload/status/Response. Для новой заявки с выключенным флагом 409/Error code=solution_creation_disabled, detail «Создание новых решений временно приостановлено. Ранее созданные заявки доступны.». Проверка после currentApplication/прав, до срока/формы; anonymous/outsider/legacy и повтор сохраняют прежние статусы. Ни один клиентский параметр не обходит флаг.
- Остальные операции и 120 схем не меняются; добавляются независимые сценарии. Старый Angular уже запрещает создание по canCreate и корректно открывает существующую заявку. Новый Angular уточняет только текст существующего error state; неизвестные причины сохраняют прежний общий текст. Backend/миграция → frontend. Обычные/legacy проекты продолжают прежний путь.

## Проверяемые AC и план

| AC | Предусловие и наблюдаемый результат |
| --- | --- |
| ROL01 | Migration 0033→0034 на существующих программах/решениях: флаг False, остальные доменные данные и mode неизменны; новая программа тоже False. |
| ROL02 | Eligible участник/manager без заявки при False: context запрещает создание; POST 409/C00, нет Solution/Member/Project writes. При True прежний create 201 работает. |
| ROL03 | При False captain repeat POST 200 возвращает тот же ID/name/version, currentApplication открывается; accepted member не создает вторую заявку. |
| ROL04 | False не запрещает save/file binding/invite/accept/role/revoke/team/submit существующей draft; submitted snapshot остается frozen, public/evaluation readers сохраняют прежнее поведение. |
| ROL05 | Anonymous/outsider/unknown/unsafe/legacy и права имеют прежние результаты; can_create и POST согласованы, приоритет причин проверен. |
| ROL06 | CLI preview не пишет, apply меняет флаг только выбранной программы; повтор идемпотентен, ID validation/legacy enable отвергаются. ProgramSolution/version/data/другие программы неизменны. Обычный save устаревшей карточки программы не отменяет committed enable/disable. |
| ROL07 | На PostgreSQL disable и create используют program row lock: запрос, начавшийся после committed disable, не создает; новый create, ожидавший lock при отключении, перечитывает False. Если create завершился первым, существующая заявка сохраняет доступ. |
| ROL08 | Frontend direct new route/program entry при disabled context показывает понятную причину без POST/legacy fallback; existing application открывается. Wire contract fixtures/strict types сохраняют реальные ID/прежние схемы. |
| ROL09 | Actual local HTTP/browser rehearsal отдельной synthetic программы: off → enable → create → disable → повтор/read/edit/invite/submit → re-enable. Никаких real program switches/deploy/рассылок; local storage only. |
| ROL10 | Source audit/relevant tests, migration/check, C00 both copies, frontend tests/build/lint/format и review связываются с каждым AC. У REL01 полный verdict остается открытым до полного QA01 и согласованных UI. |

Порядок реализации: metadata/migration и scoped CLI → creation/context guard → backend tests/migration/locking → синхронизация C00 и механическое уточнение Angular error text → tests/build → actual HTTP/browser rehearsal → review/evidence/PR handoff. Не зависеть от нерешенных административных исключений, D02/D03 или конкурсной eligibility; не выбирать ответы за пользователя.

## Rollout и откат

1. Backend + migration: storage mode по умолчанию legacy_project, creation flag=False, существующие данные не переносятся. Проверить совместимость старого клиента с новым контекстом.
2. Frontend после backend. На отдельной выбранной новой программе настроить solution mode/форму/сроки/команду/эксперта и пройти полный QA01; этот этап еще не выполнен для полного выпуска.
3. Только после приемки выполнить scoped command preview и apply enable для утвержденного ID. Не включать автоматически все solution программы и не привязывать разрешение к is_competitive.
4. При откате command disable для выбранного ID; сохранить solution_storage_mode=solution. Дождаться завершения команды/commit; последующие create отклоняются, existing read/writers продолжают прежние правила. Не откатывать additive column/код к версии без guard и не удалять решения. Data migration назад не является creation-only rollback.
5. После проверки можно повторно enable. Сданные снимки/публикация/версии не сбрасываются. BE10 отдельно по утвержденному списку, не входит в этот rehearsal.

## Evidence

**ROL01–ROL10 в техническом scope PASS; весь REL01 и QA01 остаются OPEN.** [Точные evidence](../qa/program-solutions-creation-switch-20261025/README.md).

| AC | Evidence и предел утверждения | Verdict |
| --- | --- | --- |
| ROL01 | TransactionTestCase миграции и actual local 0033→0034: 8 программ, 6 решений, 23 ответа, 10 участников, 5 приглашений, 12 оценок, 4 назначения, 5 файлов, 2 Project; все прежние columns/data совпали, флаг False. | PASS |
| ROL02 | Disabled context/POST и enabled create API tests; actual browser direct route/program entry, HTTP 409 и CLI enable → 201 для КЧ/хакатона. | PASS |
| ROL03 | Captain repeat без переименования/версии, accepted member без второй заявки; tests и 30 HTTP/C00 checks, currentApplication приоритетен. | PASS |
| ROL04 | При False API tests выполняют file binding/save, invite/edit/accept, transfer/remove/leave, submit и pending decline/revoke; эксперт rate/manager results и неконкурсная публикация читаются. Actual browser обеих форм сохраняет/приглашает/сдает после disable, frozen snapshot и 0/False/file bytes подтверждены. | PASS |
| ROL05 | Tests unknown/unsafe/anonymous/outsider/staff/manager/legacy, false не меняет права/сроки; payload не может передать флаг. | PASS |
| ROL06 | CLI preview/apply/повтор, выбранная программа и один столбец; errors без writes. Model.save сохраняет persisted flag, если update_fields не выбирает его явно. Два направления stale save проверены после review fix. | PASS |
| ROL07 | Два реальных PostgreSQL lock tests подтверждают блокировку worker через pg_blocking_pids, а не только старт потоков: waiting create перечитывает False после commit, waiting disable сохраняет созданную перед ним заявку. | PASS |
| ROL08 | 3 новых wire + 2 route + 1 entry tests (55 focused); существующие new/direct/owned/legacy routes и error states. Новый error text проверен в actual browser, layout не менялся. | PASS |
| ROL09 | Программы 9/10: off → enable → create → disable → сохранение/приглашения/submit → re-enable и новая draft → disable. Решения 8/10 submitted, 9/11 draft, финальные флаги False. 37 mutating browser HTTP (включая expected conflicts), JS errors=0; 30 дополнительных HTTP checks не изменили домен. Hash всех прежних данных совпал с migration baseline. | PASS |
| ROL10 | Final regression 261 PostgreSQL tests, включая 17 новых; Black/Flake8/check/migration consistency/C00 PASS. 2760 frontend tests/478 files + strict types/development build/scoped ESLint/locked Prettier 3.8.3 по 1969 files PASS. Source review выполнен, исправлена перезапись флага stale save, после исправления повторены 261 tests и 30 HTTP с перезапущенным API. Полный Linux CI нового commit ожидается отдельно. | PASS в scope этапа |

Полный основной browser путь — mobile 390; состояния team/materials/readonly без horizontal overflow при 320/390/768/1440, материалы дополнительно desktop. Paused route и program-entry modal просмотрены визуально; Mont. Browser использовал отдельную копию generated development build с единственным localhost API/WebSocket origin chunk; frontend source environment не менялся. Внешние avatars/CDN/почта/production не проверялись. Полный desktop/a11y/zoom не заявляется. Browser проход предшествовал последней защите stale program save; после нее выполнены final regression и HTTP на перезапущенном сервере, без повторной сдачи fixture.

Review: contract payload/схемы/прежние примеры сохранены; flag не дает новых REST прав и не меняет срок/состояние существующих работ. Scope исправления только creation/context и служебный flag; legacy regression включена. Test helper solution_program явно включает готовую fixture; production model/migration default проверен False. Старый publication migration test создает current fixture до downgrade и восстанавливает latest graph, чтобы новая колонка не делала тест исторической схемы некорректным. Открытых BLOCKER/MAJOR/MINOR в техническом scope не найдено; прочие gates полной feature сохраняются.

Для полного выпуска по-прежнему нужны исходный QA01, D02/D03 approval и реализация, административная политика после сдачи и конкурсная eligibility. Операторский rehearsal выполнялся только на новых local synthetic программах; реальные программы/dev/production не включались, merge/deploy не выполнялись. BE10 не выполнялся.

## Дополнение C00 1.17: история административных изменений

Перед frontend применяется миграция0035, создающая только SolutionAdministrativeChange/constraints. Исходные Project и snapshots не переносятся и не переписываются миграцией. При откате выключается создание; таблицу истории и миграцию0035 не откатывать вниз: сохраненные ревизии должны оставаться в БД. Existing solution/history/case readers/writers сохраняют свои права при creation flag=False. Это проверено на новых локальных КЧ/хакатоне, но не заменяет полный rollout/rollback первого выпуска. Реальные программы не включались.

## Дополнение C00 1.18: история исключения участника

0036 расширяет таблицу истории для remove_member и сохраняет все прежние case rows. В local rehearsal23 выбранные модели, включая историю, совпали до/после миграции. При откате сохраняются новые поля и события; reader должен понимать change_case/remove_member. Creation-only flag не выключает административные действия. Снятие/архив заявки, удаление регистрации и полный rollout/rollback первого выпуска остаются открыты. Реальные программы не включались.

## Дополнение C00 1.19: архивное участие и минимальная совместимая версия

0037 применяется до нового backend, затем frontend. Миграция сохраняет прежние23 модели и4 case/member events; архивируются только новые local fixtures явным action. После первого archive event backend/фоновые workers должны сохранять active filters, archive readers и frozen/file guards C00 1.19; более старый backend не является допустимой версией отката. Creation-only flag останавливает только новое создание. Snapshot/история/0037 не откатываются вниз; публичные и экспертные списки продолжают исключать архив. Новый organizer UI, удаление регистрации и полный rollout/rollback rehearsal первого выпуска остаются открыты.
