# BE08: первая сдача организатором

Source: services/management_project_actions.py, submission_errors/inspect_action/apply_action и test_management_project_actions.test_submit_after_deadline_validates_and_preserves_old_leader_contract. Действующий submit организатора проверяет материалы и состав, допускает позднюю первую сдачу, требует signed preview и повторной проверки под блокировками. can_apply требует хотя бы одну готовую несданную работу и отсутствие ошибок всей выборки; уже сданные работы учитываются отдельно, их дата не меняется.

Этот реализованный блок переносит только первую сдачу на ProgramSolution и не перезаписывает уже сданную работу. Смена кейса после сдачи с историей реализована отдельно в C00 1.17/BE08A. Исключение участников после сдачи реализовано отдельно в C00 1.18/BE08B. Отвязка/архив с retention реализованы отдельно в C00 1.19/BE08C1. Удаление регистрации остается следующим объемом [BE08](program-solutions-be08-admin-exceptions.md) с обязательным сохранением старых Project программ. Новый Angular UI зависит от D02 approval и в scope этого блока не входит.

## Контракт до реализации

C00 1.14.0: POST /programs/{program_id}/management/solutions/actions/preview/ и /apply/. Request: action="submit", ids (1–10000 безопасных JS IDs, сервер сортирует и удаляет повторы); apply дополнительно preview_token. Неизвестные поля/query, unsafe/bool IDs и неподдерживаемое действие отклоняются. Отдельные solution paths исключают смешение с legacy program-project link IDs; прежний projects/actions контракт не меняется.

Preview: items с настоящими SolutionRef и Issue[], ready_count/already_submitted_count/can_apply/nullable preview_token. Только organizer/admin конкретной программы, solution mode и competitive. GET/POST preview не меняет domain data. Нет обхода обязательных полей, case/team policy и файла. Срок не делает готовое решение неприменимым для существующего привилегированного действия.

Apply: токен подписан на 10 минут и привязан к actor/program/action/нормализованным IDs и fingerprint сохраненного состояния. Под блокировками program → solution → fields/members/files повторяются права, mode, competitive, token/state и все проверки первой сдачи. Измененная или неготовая выборка дает 409/solution_action_conflict; недоступный файл при окончательной проверке дает обычную C00 ошибку без частичной сдачи. Вся выборка атомарна. Обычный captain submit сохраняет deadline и final recheck после I/O; manager не получает HTTP force flag. Уже сданные работы не перезаписываются. Result: changed_count/already_submitted_count.

Responses: 200 success; 400 validation/материалы; 401 anonymous; 403 чужая роль/организатор; 404 unknown/чужой solution; 409 legacy/noncompetitive/устаревший или чужой token/state. Все ответы private, no-store. Новых моделей/миграций нет, creation switch не препятствует работе с существующей заявкой.

## Приемка

| AC | Проверка |
| --- | --- |
| SADM01 | Только organizer/admin своей программы; остальные роли/foreign IDs/legacy/noncompetitive и invalid input закрыты C00 ответом |
| SADM02 | Preview не пишет domain data, показывает точные per-solution issues и counts; все already submitted дают can_apply=false/token=null |
| SADM03 | Captain после срока получает submission_closed; organizer по signed confirmation впервые сдает готовую работу с accepted-only snapshot, 0/False и настоящей формой |
| SADM04 | Пустые required/case, неверный case, состав/регистрация/лимиты и файл не обходятся привилегией |
| SADM05 | Token actor/program/action/IDs/expiry/signature и fingerprint name/answers/team/form/policy/files проверяются; stale/replay не пишет |
| SADM06 | Bulk atomic, mixed submitted сохраняет прежнюю дату/snapshot, изменяется только готовый draft; частичная ошибка не сдает соседнее решение |
| SADM07 | Два concurrent confirm дают один успех, изменения материалов/команды/формы сериализованы program row lock; уже сданный snapshot неизменен |
| SADM08 | Обычный submit сохраняет permission, revision, deadline до/после I/O и прежние regression; legacy actions не меняются |
| SADM09 | C00 прежние 120 schemas/45 operations/161 scenarios сохранены; обе копии/генерация/API layer и strict wire tests согласованы |
| SADM10 | Реальный HTTP/JWT и final review подтверждают scope; нет Project/Team, переключения реальных программ, merge/deploy или реализации D02 UI |

Порядок: C00/spec → общий finalize первой сдачи → signed preview/apply и API → PostgreSQL tests → frontend API layer → реальный HTTP → review/fixes → draft PR. Это часть BE08/FE08, не готовность всего первого выпуска.

## Результат и requirement audit

Реализован отдельный API, прежние project actions не менялись. Общий `_finalize_submission` сохраняет прежние проверки и snapshot для капитана; поздняя ветка вызывается только из подтвержденной организаторской команды. Preview/apply используют program/solution/field/member/file locks. Review дополнительно перенес захват UserFile locks до fingerprint, поскольку метаданные файла могут иметь writer вне команд решения; итоговый HTTP прогон и PostgreSQL regression повторены на этом source.

| AC | Evidence | Verdict |
| --- | --- | --- |
| SADM01 | Direct API tests captain/member/foreign manager/expert/anonymous/staff, чужие и missing IDs, mode/input/query; настоящие HTTP 401/403 и private headers | PASS |
| SADM02 | Точные counts/SolutionRef, duplicate IDs, null token для all-submitted, incomplete bulk; HTTP hash всей fixture domain выборки до/после preview | PASS |
| SADM03 | Late captain 409 и manager 200, exact accepted-only snapshot/0/False, file URL и form snapshot; реальные обе формы | PASS |
| SADM04 | Required/case/registration/minimum tests, shared submission/file regression; unverified file на втором решении не обходит finalize и откатывает первое | PASS |
| SADM05 | Actor/program/action/IDs/signature/expiry/replay tests; семь изменений name/answers/member role/field/policy/file/profile без version bump вызывают conflict; actual stale/replay 409 | PASS |
| SADM06 | Mixed bulk сохраняет прежнюю дату/snapshot; incomplete блокирует всю выборку, ошибка окончательной проверки файла откатывает уже финализированного соседа | PASS |
| SADM07 | Два новых PostgreSQL races: confirm×confirm и confirm×captain PATCH; оба worker реально ждут program row lock по транзитивным pg_blocking_pids до снятия блокировки, допустимые ordered outcomes/snapshot проверены | PASS |
| SADM08 | Общая сдача/команда/файлы/форма и legacy actions входят в final 325 PostgreSQL tests; normal captain final deadline до/после I/O сохранен в source и прежних assertions | PASS |
| SADM09 | C00 125/47/185, прежние 120/45/161 структурно неизменны, три файла byte-identical; 30 новых wire tests, final test:ci 2793/479 + strict types | PASS |
| SADM10 | Final 42 actual HTTP/JWT checks на новых программах 19/20, решения 26/28 и anchors 27/29; прежняя выборка 11 domain моделей/Project не изменилась. Angular UI не добавлялся | PASS в API scope |

Checked by tests: 17 новых tests; промежуточный широкий прогон 324 и final 325 PASS. В frontend final `npm run test:ci`: 2793 tests/479 files и strict types PASS. Checked by build/static: Angular development build, scoped ESLint, backend Black/Flake8, Django check, makemigrations --check/--dry-run и C00 validator PASS. Locked frontend format выполняется после добавления новых файлов.

Checked through running API: [отчет](../qa/program-solutions-submit-actions-20261025/README.md), actual Django/PostgreSQL/JWT на localhost 8877. Обе формы: настройка/создание/сохранение, обычный anchor submit, закрытие срока и creation flag, captain 409, preview read-only, late draft PATCH → stale proof 409, fresh mixed confirmation 200, replay 409, all-submitted/null token и frozen PATCH. До/после hash прежних 11 моделей совпадает. Токены в evidence не сохраняются.

Review verdict: готово в описанном API scope, actionable BLOCKER/MAJOR/MINOR findings не осталось. Новых UI/states/layout нет, Design QA неприменим этому API checkpoint. D02/D03, административные изменения после сдачи, конкурсная публикация и общий QA01/REL01 остаются открытыми. Собственный CI нового commit проверяется отдельно, старый зеленый 6db9050 его не заменяет. Merge/deploy/real program rollout не выполнялись.
