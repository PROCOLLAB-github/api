# BE07: оценивание решения — контракт и план

Статус: API и модели BE07 реализованы; финальная проверка и интеграция общих административных входов продолжаются. Полный BE07/FE07 еще не закрыт. BE02–BE06 завершены отдельными checkpoints. Экспертный UI FE07 ожидает явного согласования D01; backend ведется независимо.

Current behavior проверен в project_rates/services.py, validators.py, workspace.py, expert_cabinet.py, criteria_policy.py и partner_programs/services/results.py. Критерии общие у программы; int/float имеют конечное значение и min/max, bool хранит True/False, str ограничен 50 символами. В управляемом режиме нужны все нетекстовые критерии; пустой необязательный комментарий сохраняется. Оценка своей команды запрещена в управляемом режиме. Лимит distinct raters применяется к legacy open без required_evaluators; свой уже существующий набор можно обновлять. Распределенный режим требует реального назначения. Приглашение/назначение/подтверждение N явно включает managed workspace. Срок can_rate проверяется текущим кабинетом для всех режимов.

Target: SolutionScore и SolutionExpertAssignment с настоящими FK на ProgramSolution, прежние Expert, ExpertCaseScope и Criteria. Новые методы используют solution_id; Project/PartnerProgramProject и их ID не создаются. Эксперт читает сданный snapshot и только свои значения оценки. Новые endpoints проверяют срок сервера так же, как доступность действия в кабинете. Публикация результатов и чтение чужих оценок остаются отдельной политикой BE08. Legacy endpoints сохраняют прежний payload.

Начальный совместимый контракт C00 1.3.0 добавляет:

| Endpoint | Результат/команда | Права |
| --- | --- | --- |
| GET /programs/{program_id}/solution-evaluation/ | Пагинация SolutionRatingSummary; поиск, кейс, статус своей оценки, assigned_only | Эксперт своей программы; в distributed только назначенные сданные работы |
| GET /programs/{program_id}/solutions/{solution_id}/evaluation/ | Snapshot Solution, программа, критерии с собственными значениями, criteria_revision, can_rate/причина, срок и счетчики | Видимая работа и эксперт своей программы |
| POST на тот же evaluation/ | expected_criteria_revision + scores[{criterion_id,value}]; обновленный frame | Проверка роли, назначения, состояния, срока, критериев, типа, полноты и лимита под общей блокировкой программы |
| GET/PUT /programs/{program_id}/management/solution-evaluation/experts/{expert_id}/assignments/ | Ревизия и варианты решений / полная выбранная solution_ids | Организатор своей программы; запрет чужой программы, своей команды, несданных работ, недоступного кейса и удаления назначения с оценками |

Ответы новых методов имеют существующий Error envelope. Неизвестный/чужой объект скрывается 404, видимое запрещенное действие дает 403, устаревшие criteria/assignments — 409. Схемы и независимые примеры добавляются до реализации; старые поля не меняют обязательность.

План: модели/миграция → shared criteria freeze → чтение/запись оценки и scoped visibility → реальные назначения → безопасное распределение и результаты с прежней математикой → соединение с кабинетом и управлением. Перед добавлением следующих операций их контракт дополняется в том же draft расширении 1.3.0. Открытый/распределенный режим и явный opt-in managed проверяются раздельно.

Дополнение контракта перед реализацией:

| Метод | Данные |
| --- | --- |
| POST management/solution-evaluation/allocation/ | revision, expert_ids, optional solution_ids/case_pools/seed/previous_plan_token/assignment_overrides → подписанный план, дефицит и нагрузка |
| POST management/solution-evaluation/allocation/apply/ | plan_token → program_id, новая revision, число созданных назначений |
| GET management/solution-evaluation/quota/?required_evaluators=N | Последствия изменения N без записи |
| PUT management/solution-evaluation/quota/ | revision и N; сохраненные оценки и избыточные назначения не удаляются |
| GET management/solution-results/ | Группы решений, прежние баллы/места/завершенность; только организатор, private/no-store |

Реализовано: отдельные FK SolutionScore/SolutionExpertAssignment, unique constraints и индексы; migration 0008. Все записи API сериализованы блокировкой программы; изменение критериев использует ту же блокировку. После первой оценки критерии постоянно зафиксированы, включая обычные model/admin writers. Собственные оценки доступны только эксперту программы в пределах видимости. Новые назначения исключают несданные работы, свою принятую команду и недоступные кейсы; существующие назначения с оценками защищены. Предпросмотр не пишет данные. План действует 15 минут и требует неизменной ревизии; неполный план не применяется. Пересчет использует существующий alternative_pairs, который не читает Project. Общие enable_workspace/revision корректно выбирают ветку решения, сохраняя исторические оценки при явном opt-in.

Математика вынесена в project_rates/evaluation_math.py и используется прежним results_data проектов и новым solution_results. Сохраняются проверка всех критериев, Decimal/ROUND_HALF_UP, среднее сумм завершенных экспертов, среднее по числовым критериям, отсутствие места у неполной работы, общий ранг до фильтрации и места 1/1/3 при равенстве. Нечисловые критерии участвуют в завершенности, но не добавляют баллы.

Checked by tests: локальный PostgreSQL regression — 257 выполненных tests, PASS; финальный профильный прогон — 43 PASS (33 новых сценария и 10 существующих tests результатов). Tests проверяют роли, 404 чужих работ, ревизии, NaN/Infinity/диапазон/0/False, full managed и partial open, неизменный snapshot, защиту назначений, квоты, кейсы, подпись/срок плана, reroll и три конкурентных сценария. Отдельный тест создает реальные Project и ProgramSolution в разных программах и подтверждает одинаковые результаты; существующие management results/export tests проходят после извлечения общей математики. Black/Flake8, makemigrations --check и C00 validation PASS. Linux CI на новом commit запускается после публикации; предыдущий BE06 abf23b0 прошел обе CI проверки.

Checked through running HTTP API: две отдельные локальные программы КЧ и хакатона, JWT эксперта/организатора/участника, сданный snapshot → 0/False → отклонение NaN без порчи оценки → предпросмотр и применение назначения → второй эксперт → итог 0.5 и место 1. Участник получает 403 на административные результаты; эксперт видит только собственные значения. Migration 0008 применена к локальной PostgreSQL 18 на 55439. Реальные программы и внешние письма не использовались.

Следующий checkpoint BE08 подключает общий кабинет, Django admin и after-commit уведомление. Для c15a995 завершен Linux PostgreSQL CI: 1508 tests и 39 locking tests PASS; общий CI PASS. Осталось до полного продукта: остальные административные входы, публикация материалов по текущим правилам, экспертный UI после D01 и итоговая проверка AC18/20. Аналитика/выгрузки — BE09; новая сущность в целом еще не завершена.

Requirement audit текущего блока:

| AC | Evidence | Вердикт |
| --- | --- | --- |
| AC17 | evaluation frame использует immutable snapshot; профильные API tests и HTTP обеих форм | PASS для API |
| AC18 | Типы, роли, квоты, кейсы, назначения, математика и результаты проверены; публикация и продуктовый UI впереди | PARTIAL |
| AC20 | Scope программы и настоящие FK; private results, чужие Expert/criterion/solution IDs отклоняются | PASS для новых API; общие входы еще впереди |
| AC22 | Existing project rates/workspace и management results/export tests PASS; старые C00 операции и примеры сравнены семантически с HEAD | PASS в проверенном scope |

Code review: новых блокирующих замечаний в текущем API scope после исправлений не осталось. В review исправлены PostgreSQL IN/DISTINCT ordering, разделение criterion_id/field_id, согласование общей workspace revision и opt-in, защита истории и точных значений кейса. Это не заключение о готовности всего первого выпуска.

AC17/18/20: snapshot, правильная работа/программа, свои оценки, прежние типы/границы/завершенность, назначение и критерии; AC19 — общий расчет без дублирования Project для последующей аналитики. Проверки включают negative permissions, чужие IDs, 0/False, partial legacy open / full managed, deadline, criteria conflict, atomic rollback, protected assignments, concurrent quota/scores и паритет результатов с legacy. Until checks pass этот документ не является отчетом о готовности.
