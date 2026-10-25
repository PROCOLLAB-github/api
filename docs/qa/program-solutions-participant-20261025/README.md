# QA01 PART01: участник КЧ и хакатона

Scope PASS от 25.10.2026; **общий QA01 и REL01 не завершены**. Требования/оставшиеся проверки — [матрица QA01](../../product/program-solutions-qa01.md).

Runtime: backend 1724bca4c7cf7907955312d1f4c9e6ec44316fbd, frontend e57fb04ec93fdede611712014492a529cf9172b9, C00 1.12.0. Последующие docs commits не меняют эти runtime исходники. Local PostgreSQL 18, Django settings_ci, locmem mail, localhost storage; Angular SPA 8874 → HTTP API 8871. Это не production/deploy приемка.

## Evidence

- [browser-evidence.json](browser-evidence.json): реальные browser HTTP events, программа 7 КЧ/решение 6 и программа 8 хакатон/решение 7, checkpoints, 28 mutating HTTP requests (включая ожидаемые конфликты), JS errors=[]; один успешный submit на решение. Не содержит JWT/паролей.
- [attempt-1792901599060.json](attempt-1792901599060.json): raw completed-phase invocation с FAIL на финальной проверке, прочитавшей pending до завершения DELETE. Обе сдачи и успешные DELETE уже видны в событиях. Сохранен без удаления статуса FAIL.
- [run-state.json](run-state.json): фазы и IDs; отдельно записано удаление только прежнего draft=5 до прямого HTTP прогона. Submitted=6/7 сохранены.
- [domain-evidence.json](domain-evidence.json): итоговая проверка actual database snapshots/answers/members/invitations/files, 18 настоящих HTTP checks с C00 validation, forbidden writes не изменили доменные данные; Project count unchanged, самостоятельных Team models нет. Отзыв приглашения проверен отсутствием удаленной записи, а не выдуманным status=revoked.
- [build-provenance.json](build-provenance.json): только один generated JS chunk в копии development build получил локальные API/WebSocket origins. Product environment/source и обычный build не менялись.
- [local-artifacts.json](local-artifacts.json): SHA-256 12 screenshots и трех harness sources. Screenshots находятся в Z:/Документы/PROCOLLAB-dev/design-artifacts/program-solutions-20261024/qa01-participant; sources — C:/Users/evsee/AppData/Local/Temp/ с указанными именами. Fixtures/password manifest остается только в Temp, в Git не включен.

Evidence состоит из завершенных реальных фаз и отдельной финальной проверки сохраненных submitted fixtures. Повторного заполнения или submit при resumed invocation нет. Первая попытка verifier ожидала несуществующий статус revoked; source/контракт используют DELETE. Исправлена только проверка, продуктовая логика не менялась.

Полный основной browser путь выполнен на 390 px; состояния team/materials/readonly проверены на отсутствие overflow при 320/390/768/1440 px, desktop screenshot материалов отдельно. Mont загружен; screen reader, browser zoom и полный desktop путь не заявляются. Визуально просмотрены case_championship-materials-desktop, hackathon-submitted-materials-mobile и case_championship-submitted-team-mobile. Внешняя сеть блокировалась, default avatars отсутствуют; это ограничение local harness.

Проверены: пустой draft без кейса/required answers, две вкладки с локальным вводом, actual program search + free role, принятие/отклонение через второй аккаунт, retry после version_conflict с сохранением выбора/роли, accepted/pending capacity, save 0/false/case, настоящий PDF upload/download bytes, cancel/confirm submit, immutable readonly snapshot, pending decline/revoke после сдачи, повторная сдача и прямые запреты прав.

Не заявляются: ошибки submit/focus, stale form rebase, deadline/network negatives, все role bounds/edit приглашений, race verdict, manager/public UI, неконкурсный/legacy полный путь, production CDN/рассылки, общий QA01/REL01. Полный runtime CI отдельно PASS: [PostgreSQL 1652+39](https://github.com/PROCOLLAB-github/api/actions/runs/40159104055), [General Tests/Lint](https://github.com/PROCOLLAB-github/api/actions/runs/40159100597). CI logs проверены по Ran/OK, а не только статусу workflow.
