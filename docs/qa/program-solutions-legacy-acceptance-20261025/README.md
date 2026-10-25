# QA01: несколько программ и прежние заявки-проекты

25.10.2026. AC20 и AC22 подтверждены в указанном scope. Общий QA01/REL01 остается открытым; административные исключения после сдачи согласованы пользователем и требуют отдельной реализации. [Матрица](../../product/program-solutions-qa01.md), [evidence](evidence.json), [HTTP](http-evidence.json), [фазы браузера](browser-summary.json).

## Проверенное поведение

| AC | Доказательство |
| --- | --- |
| AC20 | Captain9 работает с решениями45/47 программ30/31: разные определения, точные ответы с пробелами/pipe, int0/boolean false, свои приглашения51/52. Чужая пара program/solution дает404 для GET/PATCH/submit и ничего не меняет. Expert15 получает только свои оценки решений34/36 программ23/24 и правильные criteria IDs. Captain не получает expert права. Тот же user15 является manager23/24, но только expert34: analytics23/24 разрешена, analytics30/34 запрещена403; legacy expert list34 доступен. Контекст captain34 остается legacy_project4/link3. Совпадающие Project3/4 и Solution3/4 не смешиваются; недоступное решение дает404, правильный Project читается |
| AC22 | Два свежих Project созданы через прежний POST/PATCH: обычный3 и конкурсный4 в legacy программе34. Через действующий Angular editor сохранено название, приглашен участник, получатель принял приглашение; другое приглашение изменено и отклонено, третье отозвано. Состав каждого — captain9/member10, ожидающих нет. Обычный Project сохранен с draft=False без program link. Конкурсные поля255/256 сохранены, отмена подтверждения не сдает заявку, единственный submit POST link3 дает200 и дату сдачи. Project4 остается закрытым; ProgramSolution не создается |

Runtime backend: db7ffe4d6124b16232685fb49f77105f1436bacf; прежний local HEAD04637f6 добавлял только DRAFT acceptance документы. Frontend до исправления: f6f1ba96f369d06d502b250b98f3fbcf0963309c; после: d0b7ba6ea2087f979ca51fb0f6cb03e28d3c7845. C001.16.0 не менялся, три общих contract files byte-identical.

39 новых проверочных HTTP responses:23 multi-program,7 dual-role и9 final legacy reads;27 новых solution responses и2 корректных request bodies проверены по C00. Legacy DTO не выдаются за часть нового solution OpenAPI. Два cross-program commands отклонены404, domain mutations verifier=0.

В браузерном журнале340 responses, включая318 GET и22 команды; отдельно4 setup POST/PATCH. Эти числа включают повторные чтения при продолжении сценария. Реальное создание legacy fixtures намеренно добавило2 Project,4 Collaborator и связанные данные новой программы; утверждение «создание решения не создает Project» относится к ранее проверенному FORM пути, а не к этому старому POST /projects/.

Все ранее существовавшие строки22 выбранных доменных моделей до setup и после browser/final verification совпали по canonical digest. В выборку входят Project/Collaborator/Invite, программы/поля/регистрации/связи, все ProgramSolution/Answer/Member/Invitation, оценки/назначения обоих форматов, Expert и M2M, Industry/UserFile. Новых ProgramSolution=0. Auth/User.last_activity, cache и чтение свежих Project не входят в этот инвариант. Реальных программ, dev/production deploy, merge или переноса данных не было.

## Найденное исправление редактора

При возврате с «Команды» на «Данные для конкурсов» активная вкладка оставалась без содержимого; прямой вход в additional показывал поля. Отдельная read-only probe воспроизвела initialSelectCount=1, afterNavigationSelectCount=0 без pageerror/local request failure. Выбранный additional блок теперь загружается `@defer (on immediate)`; остальные вкладки и API не менялись.

Новый parent integration test запрещает idle callback и проверяет появление выбранной панели. Дочерний renderer в этом тесте заменен stub; настоящие поля/значения/сдача проверены в браузере. До изменения trigger — один assert FAIL, после —4/4 PASS. Первая версия test harness не определяла cancelIdleCallback; это исправлено до содержательного red run. Финальный полный frontend:2844 tests/480 files, strict C00 types, development build, scoped ESLint и locked Prettier3.8.3/2017 files PASS. Исходный HTML runtime совпадает с commit после нормализации CRLF; spec после build форматировался и затем прошел полный suite.

Native PostgreSQL legacy regression:148 tests/OK, отдельная ICU ru-RU test DB. Прочитаны assertions создания/привязки Project, доступа к detail, team permissions/freeze/min/max, переходов Invite и старой сдачи/кейсов. Это focused suite, не148 дополнительных уникальных tests сверх полного CI. Полный CI исходного backend db7ffe4: PG39 locking/vacancy +1717 full tests/OK, General1717/OK(skipped59). [PG](https://github.com/PROCOLLAB-github/api/actions/runs/40186181126), [General](https://github.com/PROCOLLAB-github/api/actions/runs/40186177144). Новые docs commits не объявляются проверенными этими же CI refs.

## Происхождение и ограничения

Сохранены11 browser invocations и завершенные фазы; это resumed acceptance, а не один непрерывный PASS. Обычный Project завершен в attempt4, legacy team —5, поля —9, отмена/подтверждение/submit —11. Последний проход без новых JavaScript errors; историческая dynamic-import ошибка остается в отчете.

- Setup1 откатился целиком из-за отсутствующего show_filter. Setup2 создал программу34 и оба Project через4 HTTP writes, затем metadata assertion ошибочно ожидал partner_program.id вместо program_id. Recovery завершил только private manifest, ничего не пересоздал и не изменил в доменных данных.
- Harness уточнен по реальным контролам: исчезающее cookie notice, native name input, searchbox/combobox, обновление получателем списка уведомлений, нормализация текста nav, возврат в editor после штатного save-draft redirect, legacy modal без role=dialog. Завершенные приглашения/сдача не сбрасывались.
- В attempt7 зарегистрирован localhost ERR_CONNECTION_REFUSED при параллельной загрузке chunks. Увеличена очередь только вспомогательного static server. В attempt6 dynamic import error при ранее наблюденном HTTP200 сохраняется как ошибка с неустановленной причиной; она не объявляется тем же доказанным отказом соединения.
- Initial final verifier неверно ожидал принятые/отклоненные записи в pending-only /invites/ list. Исправлен по действующему queryset: list пуст, history читается через detail. Это read-only ошибка verifier; данные не менялись.
- Дополнительная post-submit probe editor была перенаправлена на detail действующим guard и не считается повторной проверкой редактирования. Финальный detail readback и DB подтверждают прежний submitted путь.

Raw logs/helpers/screenshots/build metadata находятся в `Z:/Документы/PROCOLLAB-dev/design-artifacts/program-solutions-20261024/qa01-legacy`; hashes и исходные Temp paths в evidence. Credentials/JWT остаются вне Git. Origins API/WS заменены только в одном generated chunk копии development build; исходные environment files не менялись. Внешняя сеть блокировалась, поэтому avatars на screenshots отсутствуют. Проверены team и submitted states; полная desktop/a11y/zoom/production CDN приемка не заявляется.

AC18/19, D02/D03 UI, согласованные административные исключения/retention, конкурсная публикация несданных черновиков и полный REL01 остаются в первом выпуске. AC21/BE10 — отдельный последующий перенос по утвержденному списку. Новое решение пользователя не дает разрешения удалять или автоматически переносить старые Project заявки.
