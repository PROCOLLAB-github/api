# QA01: одна заявка капитана и одна команда участника

AC02 и AC08 проверены на реальных HTTP, двух независимых API-процессах и PostgreSQL. Обычный вход капитанов и участника через Angular открывает существующую заявку, в том числе при выключенном создании. Продуктовый код этого checkpoint не менялся. Общие QA01/REL01 и первый выпуск остаются незавершенными.

Backend source: `30c0d3ec1ac8e1236dd669205b97b4a2b4463fda`; frontend: `d2a2cd3f80549e7dcbc6b3e32e55fea7ead57175`; C00 `1.14.0`. Только новые синтетические программы 25/26, решения 38–41, prefix `qa01m-20261025-b080f725`. API 8877/8878, SPA 8881, PostgreSQL 18/main procollab_ci; locmem mail и блокировка внешних запросов браузера. Пароли/JWT/credential manifest не включены в Git.

| Проверка | Наблюдаемый результат | Evidence |
| --- | --- | --- |
| MR01 / AC02: одновременное создание | В каждой программе два POST от одного капитана через разные API. До освобождения строки программы наблюдались два разных PostgreSQL PID и пути `pg_blocking_pids` к контроллеру. Ответы 201/200 с одним ID; в БД одна заявка этого капитана и одна начальная запись состава. | [HTTP и четыре race proof](http-evidence.json) |
| MR02: повторное создание | Повтор POST с другим названием возвращает прежний ID, название и version=1. После выключения creation повтор тоже открывает существующую заявку. | HTTP, context GET и независимый verifier |
| MR03 / AC02: обычный вход | «мое решение» открывает правильный current_application обеих программ для двух капитанов и принятого участника; creation=False, автоматических solution POST нет. Команда находится во второй вкладке той же заявки. | [8 browser checks](browser-checks.json) |
| MR04 / AC08: два приглашения | Одному человеку направлены приглашения в две разные команды активной программы. Два одновременных accept через независимые API достигли реальной program lock до освобождения контроллера. Один 200, второй 409/already_in_program_team; ровно одно членство. | HTTP и DB verifier |
| MR05: повтор проигравшего и отклонение | Повтор accept проигравшего с актуальной invitation version=1 снова дает 409 без изменения pending/version. Обычный decline затем дает 200/declined/version=2. Победившее accepted членство сохраняется. | HTTP; final invitation IDs/status в verifier |
| MR06: изоляция и доступ | Принятый участник открывает победившую заявку; другая команда после decline дает 404. Редактор названия и приглашение участнику не доступны. Одинаковые аккаунты участвуют в двух программах без смешения solution ID. | Browser checks и C00 GET |
| MR07: контракт и прежние данные | 31 HTTP response / 24 JSON requests и 16 browser responses соответствуют C00. Три contract файла byte-identical в repos. Прежние строки 15 выбранных domain моделей совпали с baseline; Project не появился. | [Независимый verifier](domain-and-contract-evidence.json) |

Конкурентные проверки не подменены двумя последовательными вызовами: каждая из четырех гонок наблюдает оба живых запроса до освобождения настоящей блокировки строки программы. Второй worker может ждать первого, поэтому сохранены транзитивные пути к контроллеру. Это проверка указанных инвариантов, не нагрузочный benchmark и не доказательство всех AC15 submit/save/team/form races.

Прочитаны конкретные assertions текущих `SolutionCreationConcurrencyTests.test_concurrent_create_serializes_on_program_and_returns_one_solution` и `SolutionInvitationConcurrencyTests.test_acceptance_of_two_solution_invitations_only_joins_one_team`: они проверяют один ID/создание/Project и одно принятое членство с already_in_program_team, используют настоящие PostgreSQL `TransactionTestCase`/Barrier. Новая HTTP приемка добавляет авторизацию, wire contract и наблюдаемые lock paths. Эти test modules не менялись; текущий backend CI 30c0d3e уже включает их. Локальный test DB или полный suite заново ради evidence не запускались.

## Происхождение и ограничения

Начальный helper прочитал revision у envelope вместо form.revision и остановился после одного GET. PUT/создание решения еще не выполнялись. Исходный FAIL сохранен; продолжение явно проверило prefix, ID программ 25/26, отсутствие решений/полей, выключенные flags и пустую историю гонок. Программы и данные не пересоздавались.

Первый browser attempt выполнил оба капитанских входа, но во втором отдельном контексте не появилась форма login; JavaScript exception не зафиксирован, причина не установлена. Повтор с диагностикой завершил все восемь продуктовых проверок, затем упал на ошибочном ожидании вообще нулевых program POST: фактически были четыре штатных `acknowledge-welcome` от двух новых участников двух программ. Эти записи явно сохранены в отчете. Verifier заново проверил контракт и БД, классифицировал их отдельно; новая попытка для получения искусственного zero-write результата не выполнялась. В повторном browser attempt JavaScript exceptions=0; это не отменяет первого сбоя.

Основной browser путь 390 px; шесть состояний команды проверены на 320/390/768/1440 без горизонтального overflow. Скриншоты captain КЧ и member хакатона просмотрены; остальные retained локально. Remote avatars намеренно блокировались и могут выглядеть незагруженными. Browser не повторяет создание или accept двумя человеческими кликами: это отдельный реальный HTTP race, за которым следует обычный UI вход. Полные desktop flows, a11y/zoom, нагрузка, production CDN, manager/public UI и весь первый выпуск не заявляются.

Build reused из предыдущего ER checkpoint: он был собран до commit d2a2cd3f при HEAD 091d1ee1. Единственный runtime diff между refs — уже включенный expert-frame fix, его source hash совпадает; spec не является runtime. Проверены сохраненные source hashes и один patched generated origins chunk. Исходные environments не менялись. [Manifest](local-artifacts.json) хранит SHA256 raw wire, FAIL reports, screenshots и helpers.

Финально в каждой программе по две draft заявки, всего три записи состава; у проверяемого участника ровно одна команда. Accepted/declined invitation history сохранена; pending=0. Ответов, сдачи/snapshot, публикации, оценок и назначений нет; creation flags=False. Независимый verifier не менял выбранные domain rows. Он не включает auth/session/last_activity в утверждение неизменности.

Merge/deploy, новые migrations, перенос старых программ и переключение реальных программ не выполнялись. D02/D03, политика административных исключений после сдачи и конкурсной публикации, остальные QA01/REL01 остаются открытыми.
