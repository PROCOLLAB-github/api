# BE08C1: архивное участие без потери работы

25.10.2026. Backend product8bb1c28fb9d72ba7981b24e571f8b438deb9b0ab, runtime f85f610c579dd1595d085d95b07e02c1dbf96213; frontend productbe380c5aad2f25522149999d709e7a75126a6397, build runtime2ac2e7438b1efe716c546f46612ef0a3f99c00fb. [Нормативный scope](../../product/program-solutions-be08-archive.md). C00 1.19.0:145 схем/55 операций/272 независимых сценария, три shared files byte-identical.132 старые схемы,52 операции и250 сценариев неизменны; listSolutions расширен participation filter.

Signed bulk archive снимает работу с активного участия, сохраняет капитана/состав/ответы/UserFile/оценки и исходную сдачу. Все pending и назначения отзываются, включая оцененные; оценки остаются. Черновик получает отдельный archive snapshot с captured_at, сохраняя draft/submitted_at=null. Архив читается историческим составом и организатором, исключен из текущей заявки/exclusivity/оценивания/аналитики/результатов/распределения/публикации. Новая заявка проверяет прежние регистрацию/срок/форму/creation flag. Файлы архивного черновика защищены до CDN-вызова и через ORM/admin.

Проверено:

- 391 native PostgreSQL solution tests/OK.20 новых archive tests входят в391, включая3 observed-lock races archive×archive/submit/score.65 первоначальных regression tests,20 focused и2 historical migration tests — подмножества общего391, не дополнительные уникальные tests.
- 152 legacy Project/invitation/management/case tests/OK по тому же набору12 модулей, что BE08B. Старые Project handlers не менялись; Общие проверки команды используют active solution queryset и сохраняют прежние программы.
- Полный frontend после финальной коррекции mocks:2916 tests/483 files +strict C00 types/OK. Development build/scoped ESLint/locked Prettier3.8.3/2030 files PASS до отчета.103 case/member/archive/history wire checks входят в full suite:33/22/27/21; focused archive/history48 — подмножество103. Новый organizer layout/routes/SCSS не добавлялся.
- Black/Flake8 по измененному runtime/test scope, Django check, migration consistency, C00 и diff checks PASS. Финальные mock-only commits исправляют readiness/pending/effects/даты архивных примеров и семантические проверки C00. Runtime backend не менялся, что проверено diff; frontend full suite повторен. Build predates только fixture correction; generated production types/source совпадают, fixture не имеет production потребителей.

Первый focused run обнаружил stale test instance в assertion после HTTP archive; fixture перечитывается. Первый full391 обнаружил2 historical migration tests, читавших схему0033/0034 через текущую модель с новыми полями. Они используют исторические модели/полный набор полей соответствующей версии; assertions о сохранности данных не удалены. После исправления2 historical и полный391/152 PASS. Все исходные failure logs сохранены.

0037 применена только к main local `procollab_ci` и отдельной Unicode test DB. Все старые строки23 выбранных моделей и4 case/member events сохранены: `fc500f1028354a9e8697edd516762157f9907574c4dfc4467560c21d8d0cbe0a` до/после схемы и HTTP journeys. Миграция не архивировала существующие решения и не переносила/удаляла Project.

Настоящий HTTP:109 responses/53 request bodies по C00. Новые программы40/41/42:

- КЧ40: сданное решение55 с2 оценками и2 назначениями плюс пустой draft56 сняты одной bulk-командой; история5/6. Закрытый срок/creation flag=False не мешает явному снятию. Старый preview после изменения срока отвергнут, повтор apply409; исходная сдача/0/false/состав/оценки/регистрации сохранены, все назначения и pending сняты.
- Хакатон41: draft57 архивирован без submit, история7. Позднее изменение текущей формы не меняет сохраненную форму. Создано новое решение58, тот же участник приглашен/принят; current_application указывает58, старый57 доступен для чтения, active/all lists дают1/2.
- Неконкурсная42: draft59 опубликован штатным local publisher без submit, затем снят, история8. Public list становится пустым/detail404, published_at и материалы сохраняются, повтор publisher не публикует архив.

Legacy context34 остается Project4/link3; archive endpoint там409, чужая пара program/solution404. Создано5 новых Solution и4 archive events, новых Project=0. Старые case/member anchors1–4 не менялись, все creation flags новых программ в концеFalse. Двоичные файлы/CDN операции в HTTP не выполнялись; file retention проверен native API с CDN mock и ORM.

HTTP продолжен после штатного401 для нового synthetic extra captain18, созданного factory с is_active=False. Активирован только этот новый prefix-guarded аккаунт. Выполненная сдача55 не повторялась: всего один успешный submit, три успешных archive apply для четырех работ, пять созданий Solution. Неожиданный401 сохранен и валидирован, поэтому это resumed journey. Authorization/JWT/password не записывались; в Git wire скрыты11 signed proof strings, исходный wire проверялся до redaction.

`evidence.json` хранит hashes26 Python source files/helper/raw artifacts; `http-wire.json`, `migration-evidence.json`, `contract-evidence.json` разделяют scopes. Исходные logs/wire остаются локально в `design-artifacts/program-solutions-20261024/qa01-solution-archive`, private baseline/manifest — TEMP. Собственный8877 wrapper34824/worker7368 остановлен и проверен;8769/8871/8876 сохранены.

Предыдущий backend b829e526: [PG40202219920](https://github.com/PROCOLLAB-github/api/actions/runs/40202219920)39 locking +1759 full/OK без skips; [General40202216975](https://github.com/PROCOLLAB-github/api/actions/runs/40202216975)1748/OK(skipped64). Это терминальные результаты предыдущего BE08B; CI нового C1 еще проверяется отдельно.

После первого archive event допустимый backend/worker rollback должен сохранять C00 1.19 readers/active filters/frozen/file guards; schema-down и возврат к backend без архивного состояния теряют эти правила. Creation-only flag не отключает административные команды. Полный rehearsal REL01 еще открыт.

Первый выпуск не завершен: BE08C2 удаления регистрации/аудита, D02/D03 и соответствующие screens/навигация архива, конкурсные несданные черновики и полный QA01/REL01 остаются в scope. Все26 исходных AC сохранены;23 PASS, AC18/19 OPEN, AC21 отдельно BE10. Без merge/deploy/реальных переключений/переноса Project.

Финальная locked format проверка с отчетом:2035 files, failures=[].
