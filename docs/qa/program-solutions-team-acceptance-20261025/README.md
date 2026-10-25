# QA01 — команда внутри заявки и обязательная роль

25.10.2026. Подтверждены AC04/05/07/09/24/25/26 в указанном ниже scope. **Общий QA01 и REL01 остаются открытыми.** [Исходная матрица26 AC](../../product/program-solutions-qa01.md), [каноническое ТЗ](https://chatgpt.com/space/page_9632e9ed74588191b6b3e4b397d55175).

## Исправленное расхождение AC26

Согласованный D00 v3 требует выбранный ID и роль1–128. Форма уже проверяла роль, но прежний API разрешал отсутствующую/null/пустую роль. C001.16.0 намеренно ужесточает только CreateInvitation и UpdateInvitation: новая роль обязательна, хотя бы один символ непробельный, длина1–128; PATCH другой информации может не передавать role. Переданную role нельзя очистить. Значение не переписывается и пробелы валидной пользовательской роли не нормализуются сервером.

Проверка действует в HTTP serializer и transactional service. Неправильная роль дает400/validation_error до записи, versions/members/invitations не меняются. Исторические nullable role в Invitation/Member сохранены: чтение/принятие/отклонение/отзыв и частичный PATCH другого поля работают без выдуманной роли. Django admin показывает приглашения readonly; модели, миграции, legacy Project API и пользовательские записи не переписывались.

[Compatibility audit](evidence.json):128 schemas/49 operations/217 scenarios. Менялись только2 request schemas,126 schemas/все49 operation definitions прежние. В трех старых create error mocks добавлена корректная роль, чтобы сохранить проверку duplicate/max/frozen;206 остальных сценариев неизменны.8 новых сценариев проверяют границы/ошибки/историческую null role. Типы/fixtures фронта сгенерированы из той же копии C00; strict type checks запрещают missing role и clearing null. Изменений UI нет.

## Критерии и конкретное доказательство

| AC | Проверенное поведение | Доказательство |
| --- | --- | --- |
| AC04 | Команда и pending находятся во второй вкладке того же решения; отдельный выбор Team отсутствует | PART01 программы7/8: local description → Team → materials без потери; create/accept возвращают тот же solution_id; team component и общий invite form совпадают с INV runtime по source audit |
| AC05 | Капитан отправляет/правит/отзывает; получатель принимает/отклоняет; посторонний не управляет приглашением; статус/versions переходят без подмены членства | PART01 actual двух аккаунтов, INV05/06 edit409/retry200/revoke204; прочитаны конкретные asserts test_solution_invitations create/read/accept, private roles, patch/version, revoke/history, повтор processed409 |
| AC07 | Pending резервирует максимум, минимум учитывает капитана и accepted; принятие заменяет свой резерв | INV01/02: два worker ждут общий PostgreSQL program lock,201/409; retry409/team_max_size,1/1/2 → accept2/0/2. NEG: pending-only submit preparation остается draft/team_min_size и фокусирует Team; после accept разрешает переход к материалам. Прочитаны asserts tests team/reservations и submission/minimum |
| AC09 | После submit нельзя менять ответы/accepted roster или принимать pending; decline/revoke pending сохраняют снимок | PART01 frozenTail сравнивает form/answers/members до/после recipient decline и captain DELETE204. Backend asserts reject PATCH/create/accept/remove/leave/transfer; snapshot/status неизменны. Этот PASS не согласовывает административные исключения BE08 — их политика отдельно открыта |
| AC24 | Участник завершает форму, приглашение и сдачу на мобильном экране | PART01 обе формы: основной путь390px, actual поиск/выбор/роль/inbox accept/PDF/0/false/case, cancel затем один submit200; frozen state/readback. Ширины320/390/768/1440 проверяли названные состояния, полный desktop/a11y/zoom не заявляется |
| AC25 | Вкладки сохраняют ввод и кейс; сдача проверяет обе вкладки и открывает точную ошибку | PART01 сохраняет text/0/false/case после переходов и PATCH. NEG01/02 открывает Team/team-title для team_min_size и materials/field control для missing case/file/repository; из Team возвращается к нужному control. Текущие route tests и ACCESS подтверждают вкладки/очистку без переноса правок между аккаунтами |
| AC26 | Существующий modal/search по имени в программе, selected ID, required role1–128, свободная роль/подсказки, unavailable, pending/error/retry/edit/revoke | INV03–INV06 реальные обе формы/границы/409 с сохранением выбора и роли; wire requests используют ID. Новый backend role fix закрывает прямой обход UI. Current API46 responses/38 invalid requests дают400; create/PATCH не меняют15 domain моделей. Legacy null read/accept/decline/revoke и boundaries покрыты отдельными10 backend tests |

## Новая проверка и исторические refs

Новый runtime API — backend base ef314c30e3491e15b8232413000597b3f9df1456 + exact source hashes в [HTTP evidence](http-evidence.json).46 реальных responses по C001.16,38 намеренно неверных request bodies отклонены400 и самим schema validator. Только существующие synthetic программы30/31, решения45/47, приглашения51/52. Полные hashes15 domain моделей совпали; новых fixtures, Project и успешных domain writes нет.

Текущий локальный regression:340 PostgreSQL solution tests PASS, включая team/invitations/submission/evaluation.10 новых role tests проверяют HTTP, прямой service, boundaries и historical null. Первоначальный focused68 PASS предшествовал только исправлению структуры одного test context/Black; final340 выполнен после них. Ранний red сохранен в Temp: missing role реально давала201; последующие проверки имели каскадные assertions и ошибку test context. Число ранних failures не выдается за независимые продуктовые дефекты.

Frontend:2843 tests/480 files, strict C00 types, development build, scoped ESLint и locked Prettier3.8.3 PASS.6 новых wire tests проверяют1/128,400 без retry и historical null read; текущая группа team/modal/wire26 PASS. Product frontend source не менялся кроме generated types/fixtures. Макет D00 v3 и существующий путь приглашения сохранены.

Исторические источники сохранены с их границами:

- [PART01](../program-solutions-participant-20261025/README.md): backend1724bca/frontend e57fb04/C001.12, фактические фазы и отдельный resumed final readback; не один непрерывный последний запуск. Ранний final assertion прочитал pending до DELETE и сохранен как FAIL; snapshots/успешные POST/DELETE подтверждены отдельно. Submitted fixtures6/7 не пересдавались.
- [INV](https://github.com/PROCOLLAB-github/procollab/blob/79b4418d4bb891333b62c6025291af769d326b6e/docs/qa/program-solutions-invitations-20261025/README.md): runtime2ad4743/frontend0415dddd/C001.13;16 уникальных browser checks нескольких запусков и observed two-worker last-slot race. Все120 raw responses/18 request bodies заново проверены по C001.16. Начальные monitor/focus/layout harness failures не удалены.
- [NEG](https://github.com/PROCOLLAB-github/procollab/blob/79b4418d4bb891333b62c6025291af769d326b6e/docs/qa/program-solutions-negative-20261025/README.md): точные focus/minimum/tabs assertions отдельно от исправления unknown-submit alert; ранний частичный отчет не объявляется полностью зеленым.
- [ACCESS](https://github.com/PROCOLLAB-github/procollab/blob/79b4418d4bb891333b62c6025291af769d326b6e/docs/qa/program-solutions-access-20261025/README.md): current route lifecycle/privacy проверки; baseline обычный logout уже снимал view контейнером.

Audit проверил hashes всех PART/INV helpers/screenshots/raw JSON, совпадение6 копий INV JSON и прежних core definitions. Изменение create_invitation ограничено добавлением role validation; остальные service/API definitions совпадают с INV runtime после учета этой конкретной строки. team/model files и6 frontend team/modal/shared-form/use-case files совпадают с соответствующими историческими refs. Это сопоставление прежних доказательств и новая HTTP validation проверка; нового полного mobile browser прохождения на current source не заявляем.

Raw HTTP лежит в `Z:/Документы/PROCOLLAB-dev/design-artifacts/program-solutions-20261024/qa01-team-role`; helper/логи — `procollab-team-*` в Temp. Credentials/JWT в Git не включены. Нет merge/deploy/переключения реальных программ. D02/D03, submitted administrative policy, removal/detach/retention, competitive publication и общий первый выпуск остаются открытыми.
