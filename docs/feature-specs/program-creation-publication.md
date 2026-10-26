<!-- @format -->

# Создание программы и первая публикация

Дата: 27.10.2026. Целевая среда: dev, Angular + API.
Статус: реализовано в отдельных feature-ветках; публикация в dev через связанные PR.
Пользователь разрешил внедрение после аудита и исправлений макетов.

Макеты: [27 · Создание программы · черновик и публикация](https://www.figma.com/design/tvog0fpEgWgEtr7KUTjbyE/PROCOLLAB-Design-System-v1?node-id=1109-3285).
11 desktop-экранов и 3 мобильных варианта. Existing controls сверены с реальным кодом.
Runtime использует Mont; Figma использует Inter как технический preview, поскольку connector не предоставляет Mont.

## Задача и подтвержденные решения

Организатор должен самостоятельно создать программу, вернуться к черновику,
подготовить страницу, сроки и регистрацию, проверить результат и открыть прием.

- Право создания отдельно выдает администратор.
- Первая публикация требует страницы, сроков и регистрации. Форма решения, критерии и эксперты могут быть настроены позже.
- Форматы: кейс-чемпионат, хакатон, неконкурсная программа.
- Существующие оболочка, элементы, плотность и порядок разделов сохраняются.
- Реализация и PR в dev входят в scope. Production release не входит.

## Источники и совместимость

Исходные dev revisions: API `625517e615aa595ad0fe7ad90550317e959c5c3b`, Angular `72f7aa9837e18367239f1db3781c436dbf57d618`.
Перед PR включены новые dev commits: API `7b6a0c4f00d67d4acf35461a23e32900659634d3`, Angular `43f70c10`.
Они добавляют публичный reader опубликованных legacy-проектов и уточняют действующий UI решений.

Источники: `partner_programs/models.py`, `views.py`, `services/management.py`,
`services/native_registration.py`, `solution_api.py`; Angular `ui/widgets/detail`,
`ui/pages/program/detail/main`, `ui/pages/program/management`,
`ui/pages/program/management/registration`, `ui/widgets/registration-fields`,
`styles/_program-management-controls.scss`, `_ui-foundation.scss`.

Каталог по-прежнему показывает опубликованные программы. Существующие редакторы
страницы, дат, материалов, формы решения, экспертов и регистрации используются напрямую.
Старые программы не классифицируются автоматически: `program_format=NULL`.
Их технические режимы и флаг операторского отключения создания решений сохранены.

## Сценарий

1. На действующей странице программ появляется вкладка «Я организую» и заметная кнопка «Создать программу» для пользователя с правом создания.
2. Создание спрашивает название и один из трех форматов. Отмена не создает объект.
3. Создается приватный черновик без фиктивных дат; автор становится организатором, без регистрации участником.
4. Подготовка показывает три проверки: страница, сроки, регистрация. Первый незавершенный пункт получает primary CTA.
5. Настройки открывают существующие редакторы. Для черновика есть возврат к подготовке. Сохраняются только реальные изменения.
6. Предпросмотр использует действующую страницу зарегистрированного участника; создание решения, регистрация, просмотры и письма не запускаются.
7. Предпросмотр анкеты из настроек и из подготовки использует один компонент, сохраненную схему и disabled controls.
8. Подтверждение публикации повторно проверяет серверное состояние и атомарно публикует программу с текущей анкетой.
9. Успех показывает ссылки, основное действие «Открыть программу» и второстепенные настройки. Повторный запрос не публикует вторую версию.

## Правила

- Право создания: `user.has_perm('partner_programs.add_partnerprogram')`. Оно доступно в существующем Django admin пользователя/группы. Обычный staff и менеджер существующей программы не получают его автоматически; Django superuser сохраняет штатную семантику прав.
- Управление и публикация: существующий `can_manage_program`. Отзыв права создания не удаляет управление уже созданной программой.
- Черновики и вложенные program endpoints возвращают 404 посторонним. Ответы черновиков и management имеют `private, no-store`.
- Обязательные данные страницы: непустые название и описание. Обложка, логотип, город, тег и материалы необязательны.
- Для первой публикации нужны начало, окончание программы и дедлайн регистрации; окончание позже начала, регистрация еще открыта.
- Дополнительного отношения регистрации к началу или окончанию программы не введено. Действующий API допускает регистрацию после старта. Уточняющий вопрос об ограничении конца регистрации остается без ответа; сохранено исходное поведение.
- Встроенная анкета может не иметь дополнительных полей: обязательные данные аккаунта запрашивает существующая регистрация.
- Для черновика «Сохранить анкету» валидирует и сохраняет схему. Регистрация открывается вместе с программой. Для опубликованной программы существующая публикация формы остается прежней.
- Внешняя форма требует подключения администратором и валидного HTTP(S) URL. Неподключенная форма блокирует запуск.
- Новые конкурсные программы включают штатный режим/шаблон решения. Создание решения по-прежнему требует членства, открытых сроков и настроенной формы. До настройки формы участник видит объяснение и недоступное действие.
- Неконкурсная программа не требует формы конкурсного решения, критериев или экспертов.
- Создание сериализуется по автору и UUID; публикация блокирует программу и анкету, проверяет revision и актуальные данные. Ошибка откатывает обе записи.

## UI и continuity

- Оболочка Angular, sidebar, реальная карточка программы, редакторы, селекты, radio, модалки и иконки сохранены.
- Управление: Участники → Заявки/Проекты → Эксперты → Результаты → Аналитика → Настройки → Сертификаты. Подготовка не добавлена восьмой вкладкой.
- Карточки 20/16 px, заголовки 16/24, компактные действия 32 px, существующие скругления и tokens.
- Главный CTA заполнен фиолетовым; вторичные действия outline. Desktop submit справа. Mobile сохраняет DOM/focus order.
- В readiness нет фиктивного «Сохранить». На успехе primary ведет к программе.
- В существующем редакторе регистрации для draft изменены только lifecycle-статус, пояснение и название действия.
- Все 14 Figma frames проверены. Экран 05 повторяет реальную participant page; экран 08 использует ту же анкету, что экран 11.

## API contract

См. `docs/contracts/program-creation-publication.md` в API и Angular PR.

| Метод | URL                                            | Назначение                                   |
| ----- | ---------------------------------------------- | -------------------------------------------- |
| GET   | `/programs/capabilities/`                      | `can_create_program`                         |
| POST  | `/programs/drafts/`                            | `name`, `format`, `idempotency_key`; 201/200 |
| GET   | `/programs/managed/?search=&limit=10&offset=0` | Scoped список с пагинацией                   |
| GET   | `/programs/{id}/management/launch/`            | checks, blockers, warnings, revision, links  |
| GET   | `/programs/{id}/management/preview/`           | Read-only participant representation         |
| POST  | `/programs/{id}/management/publish/`           | ожидаемая revision; 400 blockers, 409 stale  |

Старый POST каталога также проверяет право создания и назначает автора организатором.
Nullable даты допускаются только у draft; DB constraint и существующий published serializer не допускают их у публичной программы.

## Acceptance criteria и audit

| AC   | Требование                                          | Evidence                                                                            | Verdict |
| ---- | --------------------------------------------------- | ----------------------------------------------------------------------------------- | ------- |
| AC01 | Создание только по отдельному праву                 | API capabilities/create/legacy POST negatives; browser no-access                    | PASS    |
| AC02 | Автор управляет, без автоматического участия        | Creation API tests + real browser editors                                           | PASS    |
| AC03 | Черновик скрыт в каталоге и по прямым URL           | API negatives, all program route boundary, no-store tests                           | PASS    |
| AC04 | Собственный список с поиском/пагинацией и возвратом | Scoped API tests; browser error/retry/search; URL query source                      | PASS    |
| AC05 | Только имя/формат, без фиктивных дат                | API three formats/null dates; browser create/checklist                              | PASS    |
| AC06 | Server blockers без частичной публикации            | API validation/rollback/concurrency tests                                           | PASS    |
| AC07 | Публикация до формы решения/оценки/экспертов        | API tests; real Angular/API full flow and participant enrollment                    | PASS    |
| AC08 | Внешняя регистрация ждет подключения                | API connected/not-connected; browser readiness disabled and explanation             | PASS    |
| AC09 | Изменение настроек требует обновления revision      | API stale page/schema and concurrent publication tests                              | PASS    |
| AC10 | Повтор create/publish не создает дубликаты          | API concurrency/idempotency; component lost-response retry                          | PASS    |
| AC11 | Preview без участия, просмотров и писем             | API no-enrollment/no-view; browser shared preview; source no writes                 | PASS    |
| AC12 | Поздняя настройка формы без ручного rollout         | API canonical solution context before/after config and operator rollback            | PASS    |
| AC13 | Неконкурсный запуск без конкурсных требований       | API publication; real Angular/API full noncompetitive flow                          | PASS    |
| AC14 | Desktop/390/360, длинное имя, empty/errors          | Browser no overflow, 255 chars, denied/retry/no-results; keyboard focus source/test | PASS    |
| AC15 | Один renderer/схема предпросмотра анкеты            | Shared component; browser saved fields order/help/disabled; registration tests      | PASS    |
| AC16 | Existing UI совпадает с реальной платформой         | Source continuity + native Mont browser screenshots + Figma audit                   | PASS    |

## Verification и границы evidence

- API: 1045 program tests и 135 project tests прошли на настоящем PostgreSQL 18 с Unicode ICU collation. После обновления dev дополнительно прошли 30 launch/public-project tests.
- Локальный harness исключает 4 существующих native PDF tests: WeasyPrint/Pango завершает Python с Windows access violation. В репозитории тесты не пропущены; полный Linux PostgreSQL CI остается обязательным.
- Django check, makemigrations --check, Black и flake8 проходят. Миграция применена на пустой локальной базе.
- Angular: полный `npm run test:ci` — 496 files / 3055 tests плюс solution contract types. После обновления dev — 37 targeted tests, build:pr и browser integration.
- Browser: installed Edge/Playwright, реальный Angular build и Django API с локальной PostgreSQL базой. Тестовые учетные записи и данные изолированы. Внешние API и изображения заблокированы; поэтому remote fallback avatars на скриншотах могут быть недоступны.
- В локальном static QA server изменяется только API origin при отдаче build; файлы окружений и исходный код не переключаются на fake API.
- Проверены case-championship и noncompetitive full flow, создание трех форматов, реальная регистрация участника, readiness, обе анкеты preview, error/retry, no access, no results, mobile 360/390, CTA text color и отсутствие page errors.
- Live dev: отдельная сессия возвращает на login. Авторизованное deployed состояние не проверено; локальные проверки не выдаются за dev acceptance.
- Figma: 11 desktop + 3 mobile, editable layers и source instances. Mont недоступен connector; не заявляется pixel-perfect совпадение метрик Inter/Mont или полный accessibility audit.

## Review / rollout

Requirement audit выполнен по исходным AC. Найденные permission/privacy, query-budget,
DI, пустое уведомление, порядок focus и цвет текста CTA исправлены и перепроверены.
Открытых BLOCKER/MAJOR по локальному evidence нет. Linux CI и live dev acceptance отслеживаются отдельно.

Порядок: API PR → миграция 0040 и API dev deployment → Angular PR → dev smoke.
Оба PR направляются в dev; merge выполняет пользователь по project workflow.
До успешного API deployment создание не следует включать в доступном Angular UI.
Администратор выдает право выбранным пользователям через Django admin.

Rollback: убрать право создания и откатить Angular UI; сохранить API privacy boundary и новую схему.
Обратная миграция nullable → NOT NULL требует явного решения по черновикам без дат;
автоматически удалять их или подставлять даты нельзя. Старый API без защиты draft откатывать поверх новых данных нельзя.

Out of scope: снятие с публикации/архивирование, копирование программ, новый общий
редактор, миграция legacy ответов, React, production release. Подключение внешней формы остается административным.

Дополнительная verification: восстановление после потерянного POST подтверждено реальным браузером: GET проверяет публикацию, устаревшая ошибка убирается, EntityCache инвалидируется и карточка запрашивается заново. Новые организаторы получают полные данные страницы без автоматической регистрации участником; 27 launch API tests на PostgreSQL и отдельный browser scenario прошли. Обычный Linux CI на предыдущей ревизии: 1879 tests, OK (75 feature skips), включая native PDF renderer. После финального исправления полного доступа организатора CI на новой ревизии требуется повторно.
