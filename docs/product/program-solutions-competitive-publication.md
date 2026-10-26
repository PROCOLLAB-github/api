<!-- @format -->

# BE08: публикация сданных конкурсных решений

Основание — подтвержденная публикация материалов в разделе «Решения» самой программы после ее завершения при включенном организатором флаге. Вопрос о несданных конкурсных черновиках уже задан и остается открытым. Этот блок реализует независимый путь **уже сданных** КЧ/хакатон работ; не определяет окончательную eligibility несданных работ и не завершает весь BE08/QA01/REL01.

До изменения publisher и публичные readers целиком исключают competitive программы. После изменения publisher под program lock устанавливает published_at только активным сданным решениям завершенной solution-программы с включенным publish_projects_after_finish. Неконкурсная ветка сохраняет текущие сохраненные материалы без искусственной сдачи. Старый Project publisher и legacy маршруты сохраняются, Project не создается и не удаляется. Архивные работы по-прежнему исключаются.

Публичные GET `/programs/{program_id}/published-solutions/` и `.../{solution_id}/` сохраняют DTO/allowlist/query/ошибки/no-store. Конкурсный список становится 200, включая пустой список; опубликованные сданные решения доступны анонимно. Конкурсные draft не выдаются даже с некорректно установленным marker. Материалы, название, форма и принятый состав читаются из действующего snapshot сдачи; новые поля и живые черновые значения его не подменяют. Административная смена кейса/состава обновляет действующий снимок по уже реализованному правилу, исходная ревизия остается в приватной истории. Закрытые оценки, назначения, анкеты и pending не публикуются.

Published_at остается readonly, идемпотентным и сохраняется после выключения флага/переноса даты окончания. GET не запускает публикацию. Сдача сама по себе не публикует работу: marker ставит прежний job. Создание новых заявок можно выключить независимо. Новых столбцов, миграций, операций, полей DTO или публичных прав на запись нет; существующие C00 public GET применяются к уже сданному конкурсному материалу. C00 получает новое описание и сценарии; временный пример 404 всего competitive списка заменяется на 200 пустого списка, остальные прежние схемы/операции/примеры сохраняются.

| AC     | Проверка                                                                                                                                                           |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| CPUB01 | Завершенные КЧ/хакатон solution программы с флагом публикуют submitted, не draft/архив; без флага/до даты marker не ставится                                       |
| CPUB02 | Публичные list/detail/search/pagination используют snapshot и принятый состав, сохраняют 0/False/file; новые живые поля/ответы не подменяют сдачу                  |
| CPUB03 | Pending/анкеты/email/оценки/назначения/приватная история не раскрываются; private endpoints сохраняют доступ                                                       |
| CPUB04 | Draft с marker, чужая/неопубликованная/архивная работа скрыты 404 для всех ролей; competitive список дает 200 без утечки этих работ                                |
| CPUB05 | Первая дата публикации сохраняется при повторах, выключении флага/creation и переносе даты; GET и первая сдача не ставят marker сами                               |
| CPUB06 | Административные case/member revisions читаются как действующий snapshot, исходный снимок остается в приватной истории; архив отзывает выдачу с сохранением данных |
| CPUB07 | Program locks сериализуют publisher с archive/другим publisher; наблюдаемое ожидание PostgreSQL проверено до снятия блокировки                                     |
| CPUB08 | Legacy Project, неконкурсные материалы, прежние данные и C00 consumers сохраняются; новые anonymous HTTP/C00 checks и регрессия подтверждают границы               |

Порядок: контракт/AC → воспроизводящие тесты → publisher/readers → PostgreSQL/static/contract → frontend shared contract и wire compatibility → фактический локальный HTTP/retention → review/fixes → draft PR. Нового Angular UI/layout нет: D02/D03 approval остаются открытыми. Реальные программы не переключаются, миграция BE10 не запускается, merge/deploy не выполняются.

## Результат и requirement audit

Реализованы существующие publisher и два public readers, без новых операций/полей/миграций. Публикация конкурсного списка расширена с временного404 на200; noncompetitive/legacy правила и приватные маршруты сохраняются. Публичный queryset повторно отбирает submitted, поэтому одного ошибочного marker у draft недостаточно. Publisher и административные writers используют прежний program lock.

| AC     | Evidence                                                                                                                                                                          | Verdict           |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| CPUB01 | Native submitted/draft/flag/date boundary и actual49/50 КЧ/хакатон: publisher0 до срока/без флага, затем1;51 noncompetitive публикует2 saved без submit                           | PASS              |
| CPUB02 | Native snapshot/live-name/answers/labels/новое обязательное поле и submitted-only pagination; actual0/False/file URL/accepted2 и поиск по snapshot                                | PASS              |
| CPUB03 | Native query capture не читает project_rates; реальные private score0/False/comments не входят в public payload, pending/email/анкеты/permissions отсутствуют; private GET401/404 | PASS              |
| CPUB04 | Native marked draft по4 ролям, чужая программа и пагинация; actual draft по5 ролям/unsafe/архив404, invalid query400 и bad JWT401                                                 | PASS              |
| CPUB05 | Native boundary/repeat/stale flag и readonly GET; actual repeat0, publication flagFalse и будущая end date не снимают marker, creationFalse не мешает reading/actions             | PASS              |
| CPUB06 | Actual signed case/member → current public snapshot, original snapshot в history; archive снимает public, сохраняя marker/сдачу/4 values и файлы                                  | PASS              |
| CPUB07 | 3 TransactionTestCase наблюдают pg_blocking_pids до unlock: publisher ждет archive; archive ждет publisher; повторный publisher ждет и сохраняет первую дату                      | PASS              |
| CPUB08 | Final432 PostgreSQL/OK без skips, отдельно4 legacy publishing/OK;2955 FE/484 files/types/build/scoped lint;97 C00 HTTP/34 bodies;25 прежних моделей совпали до/после, Project4→4  | PASS в CPUB scope |

Checked by source: publisher→program lock→active submitted selection; public GET→mode/marker/status→snapshot allowlist; существующие Angular port/adapter/repository/use cases принимают тот же DTO. Checked by tests: исходный red3/3 FAIL, промежуточный30/2 fixture errors (недобавленный вариант кейса и текст в int criterion) сохранен; после корректных fixtures30 PASS, широкий431 PASS, затем усиленные assertions нового поля/пагинации вошли в final432 PASS. Product validations и guards не ослаблялись, данные ради PASS не сбрасывались.

Checked by build/static: strict C00 types, Angular development build (прежние Sass warnings), scoped ESLint, Black/Flake8/Django check/migration consistency/C00 PASS. Shared3 файла byte-identical;156 схем неизменны,59 операций изменились только описаниями2 public GET;298 прежних scenarios неизменны, один временный404 намеренно заменен200 и добавлены6 новых (305 total). Generated types отличаются только version comment, fixtures отражают примеры.

Checked through running API:97 немокированных HTTP ответов/34 валидных тела на собственном localhost8877 API, новые49/50/51 и66–71. Publisher запускался только для этих трех program IDs с проверенным prefix, глобальный job main DB не вызывался. Старые25 моделей, включая Auth User/Project/историю/аудит C2, SHA54631ba6896d1d18cadf7f855ca1fd1b83b0a2396a72b28e2b61b720f1783169 совпал повторно после всех checks;7 прежних registration audit headers сохранены. Флаги нового создания всех трех программFalse. Owned wrapper10408/child39748 остановлены,8877 освобожден; прежние8769/8871/8876/55439 не менялись.

Not checked: новый Angular public UI (D03 pending), CDN bytes (использованы собственные metadata fixtures), production/реальная доставка и окончательная eligibility несданных конкурсных черновиков. Новый публичный дизайн не предполагается согласованным. Полный AC18/19, QA01/REL01 и первый выпуск остаются OPEN; BE10 отдельно. Это реализация и проверка CPUB, не READY TO MERGE всей feature.

Review: requirement audit выше выполнен от исходного scope и diff; actionable BLOCKER/MAJOR/MINOR в CPUB scope не осталось. Риски ограничены intended доступом по marker и200 пустой страницы вместо временного404; старый reader конкурсных решений при rollback скроет опубликованные материалы, поэтому сохраняется C00 1.21 reader/publisher. Схема не откатывается, новые миграции не нужны. Merge/deploy/реальных switches не было.

Отдельный **MAJOR integration finding** полного выпуска: после fetch origin/dev backend target587a9155 содержит новую0031_programcertificate_rendered_batch (зависит от общей0030), а feature заканчивается0038_solution_registration_removal_audit. Текущий checkout graph чист; read-only overlay новой dev migration через MigrationLoader(None) подтверждает две leaf nodes. Git merge-tree preview не имеет текстовых конфликтов, но не решает граф Django. Требуется отдельная сверка актуальных certificate models/migrations и безопасное объединение графа без перенумерации/удаления старых миграций и потери данных. Frontend dev08414b79 содержит новые certificate changes. Branch merge/rebase/force-push не выполнялись; проверки432/2955 относятся к указанным feature product refs, а не еще не подготовленной интеграции с последним dev. Поэтому готовность всей feature к merge не заявляется.
