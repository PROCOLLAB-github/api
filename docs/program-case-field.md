# Системное поле кейса программы (Production, legacy Project v1)

## Хранение и конфигурация

Отдельной модели `Case` нет. Уже существующий `PartnerProgramField` с **точным**
`name="case"` — системное поле. Единая константа: `PROGRAM_CASE_FIELD_NAME`.
`label` произвольный; `Кейс`, `Case`, `case_name`, `track` не являются служебными
именами и автоматически не преобразуются.

Обязательная конфигурация: `field_type="select"`, `is_required=true`,
`show_filter=true`. В `options` остаётся существующая строка с разделителем `|`.
Требуется хотя бы один вариант; после trim пустые варианты запрещены, включая
завершающий `|`. Дубли сравниваются через trim + casefold. API отдаёт варианты
массивом через существующий `get_options_list()`; сами сохранённые выборы
сравниваются с вариантами точно, без нечёткого сопоставления.

Выбор хранится в `PartnerProgramFieldValue.value_text`, привязанном к конкретному
`PartnerProgramProject` (Project × Program). Один проект может выбрать A в одной
программе и B в другой. Ни глобальное поле Project, ни «первая программа» для
определения кейса не используются.

Нет case definition — нет новых обязательств. Автосоздания кейсов, изменений
существующих данных, моделей, FK, колонок и миграций нет. Ограничение уникальности
`(partner_program, name)` остаётся прежним.

## Жизненный цикл

1. `POST /programs/{programId}/projects/apply/` создаёт draft без case, если он
   не передан. Первый вариант автоматически не выбирается. **Все остальные**
   required fields по-прежнему обязательны на этом этапе.
2. Если case передан явно, select validation обязательна, в том числе для пустого
   значения. Допустимый выбранный вариант сохраняется.
3. До сдачи лидер меняет case обычным PUT program fields, в пределах списка.
4. `POST /programs/partner-program-projects/{programLinkId}/submit/` проверяет
   case именно этой связи. Отсутствие/пустое значение даёт 400:

   ```json
   {"detail": "Выберите кейс перед сдачей проекта."}
   ```

   Старое значение вне текущих options даёт 400:

   ```json
   {"detail": "Выбранный кейс больше недоступен. Выберите актуальный кейс."}
   ```

5. При отказе `submitted` и `datetime_submitted` не меняются. При успешной сдаче
   конкурсного проекта case и остальные field values заблокированы, как раньше.
   Manager/expert/staff override не добавлен. Сроки и остальные условия сдачи
   сохранены; для программы без case действует прежний сценарий.

PUT и submit атомарны и блокируют строку связи. Запись case также блокирует
definition; её обычное редактирование блокирует ту же строку. Это защищает от
одновременной сдачи/записи и удаления варианта во время выбора. Повторная проверка
явного case в apply выполняется внутри транзакции перед созданием draft.

## Стабильность истории и Django Admin

Обычные `Model.save()` и admin ModelForm используют общую валидацию:

- добавить вариант или удалить неиспользуемый — можно;
- изменить `label` / `help_text` — можно;
- удалить или переименовать используемый текстовый вариант — нельзя;
- сменить `name="case"` или перенести definition в другую программу при
  существующих значениях — нельзя.

Кейсы по-прежнему создаются существующим inline `PartnerProgramField`, отдельной
Case Admin нет. Стандартный inline formset запрещает удаление использованного
case field. Стандартный экран удаления отдельного field (включая bulk action)
показывает его как protected. Неиспользованный field удалить можно.

Ограничения v1: это не database trigger. Прямые SQL, `QuerySet.update()`,
`bulk_create()` / `QuerySet.delete()` и удаление всей родительской программы
администратором могут обходить обычную model/form validation. Такие операции
не являются способом редактирования кейсов и требуют отдельной согласованной
миграции данных. Административное ручное редактирование флага `submitted` связи
не заменяет пользовательский submit endpoint. Отдельного действия массового
переименования кейса пока нет: в будущем оно должно атомарно менять options и
все соответствующие значения. Исторически некорректные значения автоматически
не исправляются; submit выдаёт контролируемую ошибку.

### Неизменённые inline при сдаче через Admin

Заморозка запрещает **мутацию**, а не повторную validation существующей строки.
Model validation сравнивает `program_project_id`, `field_id`, `value_text`
с сохранённой строкой по pk. Новый объект, перенос, смена поля или текста —
мутация; неизменённая строка может повторно валидироваться после сдачи.
Проверка допустимости самого case value при этом не отключается.

Учитывается и сохранённый `submitted` родителя, и его несохранённое значение
из текущей admin-формы. Устаревший parent instance, перенос из сданной связи
или снятие checkbox вместе с изменением полей не обходят freeze.

- `submitted=false → true`, существующие inline без изменений: Save успешен.
- `submitted=true`, inline без изменений и правка несвязанной metadata родителя:
  Save допустим.
- Одновременная сдача и изменение/добавление/удаление field value: форма отклонена;
  сначала отдельно сохранить финальные поля, затем отдельным Save отметить сдачу.
- Изменение/добавление/удаление после сдачи конкурсной связи: запрещено.

Для DELETE используется отдельный inline formset: Django не применяет обычные
model errors удаляемой формы, поэтому проверка выполняется на уровне formset и
возвращает контролируемую validation error. Правила одинаковы для generic и case.
Пользовательские `update_program_link_fields()` и `submit_program_project()`
не меняются: API PUT после сдачи по-прежнему отклоняется, даже если значения те же.

## Канонический link-scoped API

`GET /programs/partner-program-projects/{programLinkId}/fields/`

```json
{
  "program_link_id": 700,
  "program_id": 12,
  "project_id": 55,
  "submitted": false,
  "is_competitive": true,
  "submission_open": true,
  "submission_deadline": "2026-10-01T18:00:00Z",
  "can_submit": true,
  "fields": [
    {
      "id": 5,
      "name": "case",
      "label": "Выберите задачу",
      "field_type": "select",
      "is_required": true,
      "show_filter": true,
      "help_text": null,
      "options": ["AI для образования", "Цифровой HR"],
      "value": "AI для образования"
    }
  ]
}
```

Нет значения — `value: null`. Definitions упорядочены по pk. Значения другой
связи/программы не подмешиваются. GET требует authentication и ограниченного
read involvement: лидер, участник команды/приглашённый по существующему helper,
staff/superuser, manager/expert **именно программы этой связи**. Одна лишь
публичность проекта доступа к этим полям не даёт. Роли программы B не раскрывают
поля программы A, даже если проект общий. Проверка выполняется через `projects/access.py:has_program_link_read_access()`:
independent project-level access либо program-role links с точным PK запрошенной
связи. Все три исходных helper из production #732 сохраняются без изменений;
scoped singular Project detail и WRITE permissions не заменяются DEV-версией.

Metadata описывает только запрошенную связь `PartnerProgramProject`, не первую
программу общего проекта:

- `is_competitive: boolean` — `link.partner_program.is_competitive`;
- `submission_open: boolean` — `link.partner_program.is_project_submission_open()`;
- `submission_deadline: datetime | null` — результат существующего
  `link.partner_program.get_project_submission_deadline()`, в JSON ISO 8601 либо null.
  Сохраняется приоритет `datetime_project_submission_ends` и fallback на окончание
  регистрации;
- `can_submit: boolean` — `is_competitive and not link.submitted and submission_open`.

У сданной или неконкурсной связи `can_submit=false`, даже если окно сдачи открыто.
Это snapshot стадии, не authorization policy: значение одинаково для всех читателей
этой связи и не проверяет выбор case. Authoritative submit endpoint по-прежнему
проверяет лидера, case, deadline и остальные условия. GET/PUT/submit permissions
#732/#733 неизменны. `fields` в GET и ответ PUT не меняются.
Metadata берётся из уже загруженных link/program и не добавляет SQL.

Для лидера GET использует **3 SQL-запроса** независимо от количества полей:
link + program + project одним join; все values; все definitions. Для остальных
ролей добавляются ограниченные EXISTS проверки доступа, не по числу полей.
Для manager/expert измерено **6 SQL-запросов**. Регрессионный тест измеряет HTTP GET
при 1 и 20 полях для всех трёх ролей; число запросов не растёт с количеством fields.

`PUT /programs/partner-program-projects/{programLinkId}/fields/`

```json
[{"field_id": 5, "value_text": "Цифровой HR"}]
```

Формат прежний, массив, partial update допустим; ответ 200:
`{"detail": "Значения успешно обновлены"}`. Только лидер соответствующего
Project. Manager/expert/staff не получают право записи. Чужой `field_id`,
повторяющиеся IDs, неверный select, запись в сданную конкурсную связь — 400.
Чужой field ID проверяется в queryset программы до раскрытия его вариантов.
Невалидный элемент отклоняет весь запрос. Anonymous — 401, отсутствие доступа —
403, отсутствующая связь — 404. Поддерживаются GET/PUT, не POST/DELETE.

## Legacy API

`PUT /projects/{projectId}/program-fields/` сохраняется:

- одна связь — тот же атомарный механизм записи;
- нет связей — контролируемая 400;
- несколько — 409, без записи и без выбора первой:

  ```json
  {"detail": "Проект связан с несколькими программами. Укажите конкретную связь программы."}
  ```

Следующий Angular этап должен использовать `programLinkId`, не подставлять
`options[0]` на apply и показывать placeholder «Выберите кейс» до явного выбора.

Обычный `PATCH /projects/{projectId}/` без `partner_program_id` не меняет связи
проекта с программами или профили участников. Регрессия проверяет сохранение обеих
связей A/B и всех значений связанных профилей; production Project runtime не меняется.

## Совместимость фильтров и границы

`GET /programs/{programId}/filters/` возвращает case через существующее
`show_filter=true`. Manager filter `POST /programs/{programId}/projects/filter/`
и expert filter `POST /rate-project/{programId}` принимают без изменений:

```json
{"filters": {"case": ["AI для образования", "Цифровой HR"]}}
```

Внутри поля сохраняется OR semantics выбранных вариантов. Разрешения rating,
критерии и scoring не изменены. Тесты проверяют A, B, A+B и независимые значения
одного Project в разных программах.

Analytics по кейсам, отдельная модель кейса, автоматическое исправление старых
данных и frontend — следующие отдельные этапы, не часть этого PR.

## Границы production foundation

Это semantic port DEV #728 поверх production #732. Application, Team, Submission,
SubmissionExpertAssignment, Evaluation и их admin/API/migrations не изменяются.
`/programs/{programId}/manager-overview/` сохраняет новый production contract.

Поверх production #733 выполнен отдельный minimal semantic port DEV #729:
`is_competitive`, `submission_open`, `submission_deadline`, `can_submit` добавлены
только в canonical GET fields. PUT, submit и access helpers foundation не изменены.
Аналитика, `current_project_application` и evaluation deadline остаются отдельными этапами.

Перед включением на сервере нужен read-only inventory существующих definitions
с exact `name="case"` и их values: некорректные flags/options и obsolete choices
не исправляются автоматически. Никаких новых schema/data migrations в foundation нет.
