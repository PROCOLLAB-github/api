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

Этот блок еще не реализован и не принят. Основная аналитика/attention/другие экспорты остаются в полном BE09 scope.
