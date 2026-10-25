# BE09 Аналитика, виджеты и выгрузки решений

Первый блок: XLSX результатов. Общая задача BE09 еще не завершена.

## Источники и контракт до реализации

- Действующая выгрузка: `ManagementResultsExportView` → `results_data` → `export_results`. Доступ организатора программы; фильтры текущей выборки или scope=all, места до фильтрации, два листа, только полные оценки в средних. Текстовые ячейки не становятся формулами.
- До этого блока BE07 уже давал результаты реальных ProgramSolution через `project_rates.solution_results.results_data`; математика общая со старым Project, имена и кейсы из сданного snapshot. XLSX отсутствовал.
- C00 1.5.0 добавляет GET `/programs/{program_id}/management/solution-results/export/`: бинарный XLSX, JSON C00 для ошибок. Query как GET solution-results плюс scope=current/all. Права, submitted-only и program scope проверяются сервером. Старые endpoints и DTO не меняются.
- Успешная книга содержит «Решение» и «ID решения»; ни один solution_id не переносится в поле project_id. Frontend получает Blob через существующий ApiService.getFile, без нового UI до согласования дизайна.

## Проверяемые критерии блока

| ID    | Предусловие и ожидаемый результат                                                                                                               |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| EXP01 | Организатор программы solution получает XLSX с двумя листами и настоящим ID решения                                                             |
| EXP02 | Эксперт, участник, посторонний и аноним не получают закрытую книгу; другая программа и legacy mode не смешивают источники                       |
| EXP03 | scope=current повторяет search/case/status/order; scope=all снимает фильтры, сохраняя порядок; неверный scope и лишние query отклоняются        |
| EXP04 | Места и цифры совпадают с JSON; черновики отсутствуют, неполные оценки не входят в формулы средних, 0/False сохраняются                         |
| EXP05 | Имена/комментарии, начинающиеся с =, записываются как текст; числовые значения и расчетные формулы сохраняют тип                                |
| EXP06 | Пустые результаты и отсутствие числовых критериев дают корректную книгу без выдуманного рейтинга                                                |
| EXP07 | Существующая выгрузка проектов сохраняет заголовки, ID, формулы и результаты                                                                    |
| EXP08 | Frontend передает snake_case query через API port/repository/adapter/use case и возвращает исходный Blob; JSON ошибки в Blob декодируются в C00 |

## План

Контракт в обоих репозиториях → общий writer книги с явными ключами решения/проекта → scoped API → API-слой frontend → PostgreSQL и wire tests → regression старой книги → review и draft PR.

Оставшиеся BE09: аналитика решений/применимость материалов, ролевой виджет, внимание и прочие выгрузки. Экспорт не раскрывает результаты участникам и не определяет публикацию работ.

## Проверка и review первого блока

- Checked by source: общий writer параметризован ключами `solutions/solution_id` и `projects/project_id`; никакой проекции решения в фиктивный Project нет. API проверяет организатора и режим программы; результаты берутся из того же сервиса, что JSON. Все старые операции, схемы и независимые сценарии C00 семантически сохранены.
- Checked by tests: 23 PostgreSQL tests нового/старого экспорта и паритета PASS. Широкий повторный прогон: 201 PostgreSQL tests (`project_rates`, старые результаты, manager analytics и role widget) PASS. В первой широкой команде два неверных имени модулей дали loader errors; после исправления команда целиком прошла. Black/Flake8 и git diff --check PASS. C00: 74 схемы, 34 операции, 57 сценариев PASS, файлы в обоих репозиториях byte identical.
- Checked by build: frontend API-слой собирается в Angular development build. Полный Vitest: 2568 tests / 467 файлов PASS, strict C00 types PASS. Бинарный успех проходит через настоящий CamelcaseInterceptor; JSON ошибка в Blob проверяется на границе HTTP.
- Checked through running API: локальный Django/PostgreSQL/JWT на вымышленных данных КЧ и хакатона. Настоящий XLSX читается openpyxl; ID, два полных эксперта, место 1 и JSON score 0.5 согласованы; формулы/числовые ячейки сохранены; эксперт/участник получают 403, неверный scope — JSON 400. Реальная почта и production не использовались.
- Checked in browser: новый продуктовый UI выгрузки не реализован; согласование дизайна не пройдено. Полный Linux CI нового commit запускается после push. Формулы сохранены и проверены как формулы; пересчет книги в Excel отдельно не запускался, как и прежде writer использует fullCalcOnLoad.

EXP01–EXP08: PASS для API/выгрузки и API-слоя frontend. Review не выявил незакрытых дефектов этого блока. Это не приемка всей BE09 или общей feature; PR остается draft.

## Следующий блок: ролевой виджет решения

Current: GET /programs/{id}/analytics-widget/ правильно проверяет роль и считает участников через общие selectors, но работу/назначения/этапы по-прежнему читает из PartnerProgramProject/ProjectExpertAssignment. Маршрутизация экспертных входов исправляется отдельно через публичное read-only solution_storage_mode detail. Это не исправляет старые нулевые счетчики виджета.

Target: сохранить endpoint, role priority organizer → expert → participant, отсутствие polling/записей, геометрию и controls. Legacy ответ остается прежним. Solution ответ получает явный storage_mode=solution и настоящие ссылки/показатели решения, без fake Project полей. До runtime реализации описать в C00 независимую схему ветки solution и сценарии всех трех ролей; frontend читает discriminated union. Сначала backend и frontend без включения реальных программ, затем общий QA.

Источники правил: role_analytics.py; analytics.\_solution_rows (distributed требует завершенных реальных назначений, open отмечает evaluated по первой оценке); project_rates.evaluation_math.complete_values и solution_evaluation.snapshot_name/snapshot_case; selectors принятого состава BE08. Новый independent stage machine не вводится. Баллы, личности экспертов и регистрационные ответы в виджет не входят.

| AC    | Наблюдаемое требование                                                                                                                                                                                                 |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| WID01 | Приоритет и программа роли прежние; outsider/foreign Expert IDs/клиентские role claims не дают доступа                                                                                                                 |
| WID02 | Команда определяется капитаном/принятым составом своей заявки, pending не дает членство; неоднозначность возвращает 409 вместо первой строки                                                                           |
| WID03 | Участник получает SolutionRef и название/кейс сданного snapshot; чужая программа, Project и действующий live label не подменяют работу                                                                                 |
| WID04 | Стадии none/not_submitted/submitted/review/evaluated и not_applicable сохраняют смысл; неконкурсной не требуется искусственная сдача                                                                                   |
| WID05 | Expert assigned/remaining основаны на его реальных SolutionExpertAssignment; незавершенные/not_ready остаются в остатке, 0/False завершают критерии, open/noncompetitive counters null; deadline не меняет факт оценки |
| WID06 | Organizer считает ProgramSolution, submitted и уникальных зарегистрированных людей без принятой команды; неприменимое submitted в noncompetitive null                                                                  |
| WID07 | GET не записывает данные, число запросов ограничено и не растет на каждую работу; legacy regression и private payload checks проходят                                                                                  |
| WID08 | Три прежние UI-роли показывают корректные подписи/ссылки/нулевые и неприменимые состояния; browser обеих форм/mobile, source/tests/build/review фиксируются отдельно                                                   |

## Проверка и review ролевого виджета 25.10.2026

Реализован отдельный solution_role_analytics, подключенный после прежней проверки роли. C00 1.7.0 фиксирует один существующий GET и две независимые формы успешного ответа: legacy остается прежним, solution содержит storage_mode и настоящие SolutionRef/счетчики. Ошибки существующего endpoint сохраняют DRF detail и status; клиент показывает безопасный текст по статусу. Успешный приватный ответ имеет Cache-Control: private, no-store. Новых записей, событий или polling нет.

| AC | Реализация / evidence | Verdict |
| --- | --- | --- |
| WID01 | require_widget_role до выбора сервиса; tests priority, outsider, foreign expert, query claims и anonymous | PASS |
| WID02 | scoped ownership query по captain/accepted members, максимум две строки; pending исключен, multiple/legacy-only возвращают 409; API tests | PASS |
| WID03 | snapshot_name/snapshot_case и признак кейса из сданной формы; test измененной live подписи/имени, API schema и реальные browser ссылки | PASS |
| WID04 | общий complete_values и прежние правила distributed/open; API tests draft/no criteria/first score/noncompetitive/after deadline, browser обеих форм и сохраненного noncompetitive | PASS |
| WID05 | настоящие назначения своего Expert.user, только собственные оценки; 0/False, второй эксперт/квота, not_ready и null tests | PASS |
| WID06 | ProgramSolution aggregate и принятый SQL membership; уникальные регистрации, pending, historical Project и noncompetitive null tests, browser реальные счетчики | PASS |
| WID07 | tests всех ролей: не более 14 queries, число не растет после добавления восьми работ, отсутствуют INSERT/UPDATE/DELETE; old body/schema/privacy regression | PASS |
| WID08 | прежняя геометрия/controls и SCSS, C00 union на frontend; 21 component + 8 HTTP wire tests, реальный browser трех ролей и 320/390/768/1440 | PASS |

- Checked by source: legacy services не переписаны; поля решения не проецируются в Project. Ownership и строка читаются одним scoped query без второго unscoped get. Privacy ограничена ссылкой/именем/кейсом/стадией; критерии, оценки, эксперты и регистрационные ответы не сериализуются. Все прежние 74 схемы, 34 операции и 59 сценариев C00 структурно сохранены; OpenAPI/примеры/README обоих repos byte-identical.
- Checked by tests: финальный PostgreSQL прогон 214 tests (новые 15, legacy role widget, program detail и project_rates) PASS после review selector. Первый запуск финальной команды имел loader error из-за неверного имени test_role_widget; исправленный test_role_widget_api прогнан целиком. C00: 85 schemas / 35 operations / 72 scenarios PASS. Black/Flake8 пяти измененных Python файлов, makemigrations --check --dry-run и manage.py check PASS.
- Checked by build: frontend npm run test:ci — 2615 tests / 473 files и strict C00 types PASS; обычный Angular development build PASS, scoped ESLint 0 errors. Locked Prettier 3.8.3: 1961 LF-normalized files PASS; итоговый git diff --check обоих repos PASS.
- Checked in browser: реальные Angular/Django/PostgreSQL/JWT с вымышленными КЧ, хакатоном и неконкурсной программой. Три роли, открытие своего решения, пустая заявка/невыбранный кейс, 0/null/completed, Mont, 320/390/768/1440 без overflow; controlled network/retry и 409 без raw detail, legacy expert regression PASS. 0 изменяющих solution HTTP, JS errors отсутствуют. Evidence: design-artifacts/program-solutions-20261024/expert-v1/implementation/widget-browser-evidence.json. Начальный прогон завершился timeout на белой странице; повтор с HTTP-status/JS diagnostics полностью прошел, отдельная причина начального сбоя не подтверждена. Временная локальная роль менеджера и dev environment восстановлены.
- Not checked: полная основная manager analytics/attention, новые административные UI, публикация, полный a11y audit и релиз; этот блок их не закрывает. Новый commit требует своего Linux CI; предыдущий a10af12 прошел 1549 PostgreSQL tests + 39 locking и общий CI.

Requirement audit WID01–WID08: PASS. Review не выявил оставшихся blocking findings в этом блоке. Основная аналитика/attention/другие экспорты остаются в полном BE09 scope; вся feature и PR пока draft.

## Следующий блок: аналитика решений по кейсам, API

Current: services/case_analytics.py группирует PartnerProgramProject по точному текущему option системного case, считает уникальных зарегистрированных leader/Collaborator внутри каждого bucket, дает нулевые строки текущих options и without_case для отсутствующего/устаревшего значения. Это корректно для legacy, но не источник решений. Solution уже имеет snapshot_case/team_user_ids для сданного представления и prefetch answers/members для черновика.

Target/contract before implementation: отдельный GET /programs/{program_id}/management/solution-cases/ возвращает только агрегаты решений своей программы. C00 1.8.0 добавляется перед runtime реализацией. Доступ организатора/существующего can_manage_program; legacy mode дает контролируемый 409 C00. Старые overview/cases и DTO не меняются. Новый DTO содержит program_id, configured, submission_applicable, items и without_case; счетчик называется solutions_total, project_id/projects_total отсутствуют. Неприменимые submitted/not_submitted неконкурсной программы равны null, сохранение не требует submit. География/материалы/общая сводка/attention не выводятся из этого endpoint и остаются следующими блоками.

| AC | Предусловие и наблюдаемый результат |
| --- | --- |
| CAS01 | Только организатор своей программы/текущий admin может читать; expert, captain, outsider, anonymous, foreign program и legacy проверены напрямую |
| CAS02 | Каждое ProgramSolution учитывается ровно один раз; текущие options идут в прежнем порядке, включая zero; пустой/устаревший кейс попадает в without_case |
| CAS03 | Submitted читает кейс и принятый состав из snapshot; draft из собственных answers/members; изменение live данных не переписывает сданный источник |
| CAS04 | Уникальные зарегистрированные captain/accepted members внутри bucket; повторное историческое членство, pending, чужая программа и Project не увеличивают состав решения; регистрация уже защищена DB unique(user, program) |
| CAS05 | Для noncompetitive submission_applicable=false и оба submission counts null, реальное сохраненное решение учитывается без искусственной сдачи |
| CAS06 | GET не пишет, не раскрывает ответы/оценки/контакты, Cache-Control private/no-store; запросов ограниченное число, без роста на каждую работу |
| CAS07 | C00 schema/examples проверяются обеими сторонами; frontend port/repository/adapter/use case передают настоящие агрегаты, 0/null и C00 errors через реальный HTTP interceptor |

План: контракт/примеры → scoped service/API → PostgreSQL/schema/legacy regression → frontend API layer/wire/types/build → review и обновление draft PR. Новый продуктовый UI в этот блок не входит; его browser приемка не заявляется.

## Проверка и review аналитики кейсов 25.10.2026

Реализовано в services/solution_case_analytics.py и SolutionCaseAnalyticsView. Доступ и явный solution mode проверяются до чтения агрегатов; неизвестные query отклоняются. Snapshot case/team используются для submitted, живые ответы/принятые members для draft. Регистрации выбираются только этой программы, люди уникальны внутри bucket. Legacy services/DTO не переписаны. Noncompetitive учитывает сохраненную работу со submitted/not_submitted=null.

| AC | Evidence | Verdict |
| --- | --- | --- |
| CAS01 | API tests manager/admin/participant/expert/outsider/anonymous/foreign/legacy и HTTP JWT двух форм/неконкурсной | PASS |
| CAS02 | tests current option order/zero, empty/obsolete/missing value и сумма buckets = ProgramSolution count | PASS |
| CAS03 | tests submitted snapshot после намеренно измененных live case/captain/members; draft case из своих answers | PASS |
| CAS04 | tests registered accepted/pending/unregistered, historical повторное членство, legacy Project и другая программа того же капитана | PASS |
| CAS05 | API test сохраненного draft и HTTP noncompetitive program=6: null submission counters, ни одного submit | PASS |
| CAS06 | API test не более 10 queries с тем же количеством после восьми дополнительных решений, нет INSERT/UPDATE/DELETE, exact schema и private/no-store | PASS |
| CAS07 | C00 88/36/80; прежние 85/35/72 структурно сохранены и обе копии byte-identical; 12 real HTTP interceptor/error/unsafe-ID frontend tests | PASS |

Checked by tests: финальный PostgreSQL прогон 37 tests (9 новых solution cases, прежняя case analytics и solution widget) PASS. Первые две ошибки новой fixture касались существующего DB unique регистрации и не настроенного второго option; fixture исправлена, runtime assertions сохранены. Black/Flake8 измененных Python и manage.py check PASS. Frontend полный npm run test:ci — 2627 tests / 474 files и strict C00 types PASS; Angular development build и scoped ESLint PASS. Locked Prettier 3.8.3: 1963 LF-normalized files без нарушений; итоговый git diff --check PASS.

Checked through running API: настоящий Django/PostgreSQL/JWT, КЧ program=3 и hackathon=4 с одной работой и принятым зарегистрированным составом 2/1, noncompetitive=6 с одной сохраненной работой и составом 2. Ответ соответствует C00; participant/expert 403, anonymous 401, private/no-store; 0 изменяющих HTTP. Первый запрос пришел до завершения старта локального сервера, повтор после Listening прошел; сервер не перезапускался повторно. Пользовательские/production данные не использовались.

Checked by source/review: источник строго program-scoped, настоящий ID программы, нет Project полей/ID, контактов, оценок и сырого массива ответов. UI не менялся; browser приемка нового экрана неприменима. Полный нагрузочный benchmark больших программ не выполнялся; тест гарантирует число запросов, не постоянный объем памяти. Blocking findings блока не обнаружены. Общая manager analytics/attention/материалы/прочие выгрузки, подключение frontend экрана, публикация и первый выпуск по-прежнему не завершены.

## Основная manager analytics: требования до реализации

Current sources: analytics.py считает Project links/ProjectScore/ProjectExpertAssignment, case analytics уже имеет отдельный solution API. Participant selectors уже выбирают принятый состав решения; definitions посещения/onboarding/региона и 30-дневного окна активности существуют. assignment_analytics.py задает waiting_since=max(assigned_at, submitted_at), pending/not_ready/completed, пять дней до дедлайна и 24/48h attention. evaluation_math.complete_values — общая проверка всех критериев, включая 0/False/пустую запись комментария. program_report.Report защищает XLSX строки от формул и сохраняет числа. Обычная форма решения не имеет отдельного Project.region; география участников остается по существующему user.city, география проектов не подменяется географией решений.

Before/after API: C00 1.9.0 до runtime реализации добавляет GET management/solution-analytics/, assignments/, assignments/{assignment_id}/, solutions/ и export/. Новые агрегаты/страницы/книга содержат SolutionRef и solution IDs. Старые overview/attention/Project DTO не меняются. Доступ can_manage_program, явный solution mode, C00 errors и private/no-store. People attention продолжает использовать существующие scoped selectors; новые solution списки покрывают case drilldown, not_submitted и awaiting_evaluation. Отправка напоминаний/разрушающие команды и новый UI остаются отдельными блоками.

Target: сводка, воронки, оценивание/просроченные эксперты, активность, кейсы и покрытие полей читают ProgramSolution. Distributed завершенность требует реального назначения и complete_values; open сохраняет первую оценку. Неприменимые noncompetitive submission/evaluation и open assignment aggregates равны null. Один solution учитывается один раз. Покрытие поля — описательная статистика присутствия ответа через empty_value (0/False являются ответами), а не новая проверка готовности/доступности файла. Applicable/required_applicable берутся из формы каждого решения (snapshot submitted/current draft); новое required поле не становится пропуском сданной работы. Для отображения метаданных stable field ID используется текущая definition, а для удаленной — первая сохраненная definition; содержимое сданного решения от этого не меняется.

| AC | Предусловие и наблюдаемый результат |
| --- | --- |
| ANA01 | Прямые вызовы всех пяти API защищены manager/admin, программой и mode; participant/expert/outsider/anonymous/foreign IDs не раскрывают данные |
| ANA02 | Summary/funnel считают реальные solutions и уникальный registered accepted состав; Project и pending не увеличивают их; zero/empty не превращаются в ошибку |
| ANA03 | Distributed completed/partial/awaiting используют реальные назначения/required_evaluators и общую complete_values; own 0/False, blank comment row, no criteria, другой эксперт/программа проверены |
| ANA04 | Open сохраняет первую оценку и null assignment aggregates; noncompetitive дает null submission/evaluation aggregates и учитывает сохраненные drafts |
| ANA05 | Waiting/delayed experts сохраняют max двух времен, отсутствующий timestamp, 24/48h, порог пяти дней и deadline severity; GET не меняет статусы |
| ANA06 | Поля/материалы учитываются только там, где применимы; submitted snapshot неизменен, новое required поле затрагивает draft; 0/False answered, пустое необязательное не становится missing required |
| ANA07 | Activity использует 30 дней и настоящие submitted_at; case aggregates совпадают с C00 1.8; отсутствующий Project.region не выдается как вымышленная география решения |
| ANA08 | Scoped solution list сохраняет search/case/scope/submission/pagination, реальные snapshot names и safe captain поля; count соответствует выборке, noncompetitive attention неприменим |
| ANA09 | Manager assignments/detail используют настоящие SolutionExpertAssignment и Expert.user; scope all/completed/pending, score-row presence и revision-free readonly detail не подменяют IDs |
| ANA10 | XLSX program/solutions/submitted/scores содержит настоящие IDs, snapshot fields/answers и ту же сводку; строки защищены от формул, числа/0/False/partial scores не теряются |
| ANA11 | Число запросов ограничено и не растет на каждую работу, GET не пишет, legacy regressions проходят; large-volume benchmark отдельно не заявляется |
| ANA12 | C00/независимые сценарии синхронизированы; frontend API layer передает реальные DTO/0/null/query/Blob/error, строгие типы и build проходят; новый UI не заявляется готовым |

План: контракт и независимые примеры → общий scoped read context и API → книга на существующем безопасном writer → PostgreSQL/HTTP/schema/legacy tests → frontend API/wire/types/build → requirement audit/review → draft PR. Подключение существующего экрана и browser acceptance следуют после готовности всех нужных данных, без фиктивной проекции Project.

## Проверка и review основной manager analytics

Реализованы SolutionAnalyticsContext, пять scoped readonly/export API и solution_program_report на существующем Report writer. C00 1.9.0 зафиксирован до реализации: 110 schemas / 41 operations / 113 scenarios; прежние 88/36/80 структурно сохранены, обе копии byte-identical. Старые Project overview, assignment, attention и report services не переписывались. Shared SolutionAnalyticsAPIView сохраняет существующий C00 1.8 endpoint кейсов, добавляя только общие проверки доступа/private cache и преобразование datetime в wire strings.

| AC | Evidence | Verdict |
| --- | --- | --- |
| ANA01 | direct API matrix всех пяти endpoints: manager/admin, captain/expert/outsider/anonymous, legacy; чужие assignment/solution IDs и ID за safe range дают 404 без выдачи данных | PASS |
| ANA02 | API summary/funnel/attention tests accepted/pending/Project/другая программа, zero/empty; HTTP КЧ/хакатона/noncompetitive | PASS |
| ANA03 | actual rate 0/False/blank comment row, второй эксперт/квота, unassigned/invalid scores/no criteria tests; общий complete_values | PASS |
| ANA04 | open первая оценка, null aggregates, сохраненный noncompetitive draft и неприменимый attention API tests/HTTP | PASS |
| ANA05 | tests max assigned/submitted, 25h/24/48h, пять дней до deadline/warning/critical, not_ready null waiting; missing historical stamp проверен in-memory без снятия DB constraint нового submitted | PASS |
| ANA06 | новая required definition применима только draft; submitted 0/False answered, необязательная file не считается missing required; applied snapshot/current field metadata | PASS |
| ANA07 | 30-дневное окно/zero days/реальный submitted_at tests, cases parity с 1.8, Project.region не попадает в summary | PASS |
| ANA08 | count/page/search/case/submission/scope и snapshot name tests, invalid query/offset и waiting reason; фактический HTTP трех программ | PASS |
| ANA09 | реальные SolutionExpertAssignment + Expert.user, scope/status/score-row presence tests; targeted detail после review загружает только solution своего scoped assignment | PASS |
| ANA10 | настоящие XLSX program/solutions/submitted/scores, IDs/summary/snapshot answers/0/False/partial scores/no formulas; historical registration reading regression | PASS |
| ANA11 | не более 30 queries для summary/list/assignments, одинаковое число после восьми работ, нет business writes; 114 PostgreSQL tests затронутой/legacy аналитики и отчетов PASS | PASS |
| ANA12 | 47 новых HTTP wire tests и 5 прежних export tests PASS; полный frontend 2674 tests / 475 files и strict C00 types PASS, development build и scoped ESLint PASS | PASS |

Checked by tests: широкий PostgreSQL прогон 114 tests PASS, после review scoped detail/score author query повторно 15 новых tests PASS. Первая новая fixture пыталась удалить уже заблокированные критерии после оценки; no-criteria выделен в допустимое исходное состояние, защита Criteria сохранена. Black/Flake8, makemigrations --check --dry-run, manage.py check и C00 PASS. Полный frontend/сборка указаны отдельно выше. Locked Prettier 3.8.3: 1965 LF-normalized files PASS; git diff --check обоих repos PASS.

Checked through running HTTP API: реальный Django/PostgreSQL/JWT на вымышленных КЧ=3, хакатоне=4 и noncompetitive=6. Summary/cases parity, принятый зарегистрированный состав 2/1/2, actual solution list и assignment/detail, нулевой остаток завершенных оценок и noncompetitive null, participant/expert 403 и anonymous 401; все четыре книги читаются openpyxl, summary и ID согласованы, formula cells отсутствуют. Книга программы имеет 14 листов, solutions/submitted — 4, scores — 2. Evidence manager-analytics-http-evidence.json и manager-analytics-program-*.xlsx в design-artifacts/program-solutions-20261024/expert-v1/implementation. 0 изменяющих HTTP, реальные сообщения и production не использовались.

Checked by source/review: новые DTO/книга используют SolutionRef и solution_id; общий расчет завершенности/просрочек и безопасный writer сохранены. На review устранены загрузка всех решений для одной assignment detail, unsafe integer до SQL и повторное чтение пользователя автора оценки (имя выбирается вместе с исходной записью). В старом поле Criteria и прежней книге поведение не изменялось. Новых blocking findings этого API-блока не осталось.

Not checked: новый frontend экран и его browser acceptance, reminder confirmation/delivery, destructive management actions, оставшаяся публикация/QA01/REL01. Этот блок — полный набор указанных пяти read/export API, не готовность всей BE09/FE08. Large-volume memory/load benchmark и пересчет книги внутри Excel не выполнялись. Default legacy_project и реальные программы не переключались.

Предыдущий опубликованный f75da24 прошел Linux PostgreSQL CI 40146313783: 1573 full-suite tests и 39 locking tests PASS; общий CI 40146310069 на момент следующего checkpoint еще выполнялся. Новый commit основной аналитики требует собственного CI, результат предыдущего не подменяет его проверку.

## Напоминания участникам без команды

Current behavior: существующий POST `/programs/{pk}/manager-overview/attention/participants-without-team/{reminder-preview|reminders}/` уже выбирает в solution mode капитанов/принятых участников по ProgramSolution/ProgramSolutionMember. Ожидающее приглашение не создает членство. Однако общий текст предлагает создать проект.

Target behavior: только в solution mode текст предлагает «Создайте решение или присоединитесь к команде». Это касается КЧ, хакатона и неконкурсной программы. Legacy mode сохраняет «Создайте проект». Ссылка остается текущим `/office/program/{pk}/members`. Категория participants-without-visit сохраняет прежний текст и адрес программы.

Контракт before/after: endpoint/method, request selection/search/token, response preview/token/counts/recipients, ошибки и manager/admin permissions не меняются. Меняется только значение preview_text и соответствующий текст сохраненного уведомления/письма. C00 1.9.0 не расширяется: это исправление существующего участнического flow. Миграция не нужна. Angular consumer продолжает показывать server preview_text; новый UI D02 ожидает отдельного согласования.

План: mode-aware текст общего message_for → PostgreSQL tests реального preview/confirm/outbox/delivery на locmem email → regression существующих attention actions и membership → review. Реальные письма не отправляются. Напоминания экспертам о решениях, новая категория решений и destructive commands не входят в этот локальный блок и остаются впереди.

| AC | Проверяемое поведение |
| --- | --- |
| ATT01 | Preview solution-программы адресован только зарегистрированным пользователям без принятой команды этой программы; pending приглашение и исторический Project не подменяют членство |
| ATT02 | КЧ/хакатон/noncompetitive используют «Создайте решение», legacy — «Создайте проект»; пути, структура ответа и visits-сценарий сохранены |
| ATT03 | Confirm повторно проверяет состав, создает outbox после валидного preview; повтор token не создает вторую рассылку, очередь запускается после commit |
| ATT04 | Вступивший в команду после preview исключается на confirm, вступивший после confirm — при delivery; письмо повторно не отправляется |
| ATT05 | Локальная доставка содержит solution-текст и рабочий программный путь; реальные SMTP/Celery не используются в проверке |
| ATT06 | Прямой API сохраняет manager/admin program scope: участник, посторонний и аноним не получают preview/confirm; неверная программа не раскрывает данные |

### Verification и review участнических напоминаний

| AC | Evidence | Verdict |
| --- | --- | --- |
| ATT01 | Реальный preview API: капитан/принятый участник исключены, pending и участник с историческим Project включены, чужая программа исключена; preview не создает outbox | PASS |
| ATT02 | API matrix case_championship/hackathon/noncompetitive/legacy; visits сохраняет текст и программный путь | PASS |
| ATT03 | Confirm API и captureOnCommitCallbacks: сохраненные source user IDs/text/path, один durable notice и один enqueue при повторе token | PASS |
| ATT04 | Принятый member после preview дает skipped=1 на confirm; капитан нового решения после confirm отменяет delivery с attempts=0 | PASS |
| ATT05 | Locmem delivery: solution-текст, существующий /members URL, один приватный адресат и одно письмо при двух вызовах; sent/attempts/emailed_at сохранены | PASS |
| ATT06 | Реальные прямые API checks anonymous=401, participant/outsider/wrong-program=403, staff=200; outbox без прав не создан | PASS |

Checked by tests: 8 новых PostgreSQL tests PASS; общий повтор с существующими attention actions/analytics — **107 tests PASS**, включая эти восемь. Команда: `python procollab-test-unicode.py partner_programs.tests.test_solution_participant_reminders partner_programs.tests.test_attention_actions partner_programs.tests.test_attention_analytics_api`; локальный PostgreSQL 18, порт 55439, ICU test DB. Log: `C:/Users/evsee/AppData/Local/Temp/procollab-solution-participant-reminders-regression.log`. Black/Flake8 только измененных Python-файлов и git diff --check PASS.

Checked by source/review: endpoint → managed_program → selection/preview → подписанный token → confirm lock/recheck → on_commit/outbox → delivery recheck прослежен; код изменяет только mode-aware текст message_for. Angular analytics-drilldown показывает server previewText, response/payload/permission/path не менялись. Blocking findings этого локального блока не обнаружены. Build неприменим к изменению текста Python; новая схема или migration не требуется.

Not checked: новый manager Angular UI и его delivery interaction, внешний SMTP/Celery, production. Новые напоминания экспертам о решениях и остальные BE09/FE08 остаются незавершенными; этот результат не означает готовность всей feature или прохождение нового Linux CI.
