<!-- @format -->

# QA01: удаление регистрации с сохранением решения

25 октября 2026 года. BE08C2: signed удаление регистраций, независимый аудит и retention работ. Это checkpoint первого выпуска; весь BE01–BE09/FE01–FE08/QA01/REL01 еще не завершен.

Product refs: [backend abfb7c7e](https://github.com/PROCOLLAB-github/api/commit/abfb7c7e8584365cfe5846618cc03af719cc6fad), [frontend 7e5bf118](https://github.com/PROCOLLAB-github/procollab/commit/7e5bf1183bb15f3d99b030854df8b6bca11c4cb7). [C00 1.20.0](../../contracts/program-solutions-v1/README.md):156 схем/59 операций/297 независимых сценариев. Все55 прежних операций и272 сценария сохранены; две схемы истории расширены совместимо. Три shared файла byte-identical. [Scope BE08C2](https://github.com/PROCOLLAB-github/api/blob/abfb7c7e8584365cfe5846618cc03af719cc6fad/docs/product/program-solutions-be08-registration-removal.md).

## Проверенный объем

- Native PostgreSQL:417 solution tests/OK без skips, включая26 новых (23 функциональных,2 наблюдаемых гонки,1 historical migration). Отдельно152 legacy tests/OK по прежним12 labels Project/team/invites/management/case lifecycle. Эти числа не складываются с предыдущими22/416 прогоном.
- Frontend:2948 tests/484 files, strict types, development build и scoped ESLint PASS. В том числе135 case/member/archive/history/registration wire tests (33/22/27/22/31). Locked Prettier3.8.3 до report проверил2037 файлов; финальная проверка с report:2042 файлов PASS.
- Actual HTTP:74 schema-valid responses и44 valid requests, включая401/403/404/409, подпись, replay, score drift, display-name drift, pending-only, submitted member, captain bulk archive и регистрацию без решения. Набор включает первые68 ответов; завершенные mutations не повторялись. Финальные6 ответов сняты после restart API с финальным fingerprint.
- Local0038:23 модели,58 решений,4 архива,8 прежних case/member/archive events,4 Project и8 UserFile сохранены. SHA до/после `717c9a664170764394fd1f9a256fca7c78fa42d929abe0e85a4557be1f684e3d`. Миграция не удаляла и не архивировала старые записи.

Новые программы43/44/45: КЧ, хакатон, неконкурсная. Работы60/63 сняты после удаления регистраций их капитанов;63 остается draft без submit. В60 до архива отдельно отозван pending и исключен участник после сдачи: исходный/новый состав сохранен в истории, ответы и оценки string `0`/`False` остались. Назначения сохранены при исключении участника и сняты при архиве. Принятое приглашение сохранено, но доступа к материалам исключенному участнику не дает. Работы61/62 остаются draft с материалами и капитаном после удаления регистрации участника. Семь audit headers включают удаления без решения, manager/expert registration и сохраненные роли; шесть новых per-solution events. Все новые creation flags=False. Исходные23 модели совпадают с baseline и после HTTP; новый Project не создавался. Fixture IDs не относятся к реальным программам.

Архивные составы и снимки не меняются при последующем удалении регистрации. Смешанные legacy links блокируют всю новую команду. Auth User, manager/expert, другие программы и Project handlers сохраняются. Original26 AC strings неизменны;23 PASS: AC01–17/20/22–26, AC18/19 OPEN, AC21 отдельно BE10. Дополнительные admin tests не подменяют исходные критерии.

## Ограничения и воспроизводимость

Сохранены ранний focused log (31 FE tests PASS), промежуточный416 и финальный417, первые68 и финальные74 HTTP-ответа. Ошибка расположения negative TypeScript directive была видна в terminal output и исправлена до финальных проверок. Первые31 FE focused tests прошли; type assertion исправлена до полного2948/types/build. Итоговые assertions не ослаблялись, skips на PostgreSQL отсутствуют. Raw logs/helpers находятся в `Z:/Документы/PROCOLLAB-dev/design-artifacts/program-solutions-20261024/qa01-solution-registration-removal`; SHA перечислены в [evidence.json](evidence.json). [HTTP wire](http-wire.json) проверен до удаления signed proof strings; 25 значений скрыто только в Git-копии, Authorization/JWT/password не записывались. Private baseline/manifest остаются в TEMP; migration helper повторно не запускать.

Owned API8877 остановлен; прежние8769/8871/8876 не перезапускались и не доказывают текущий product. Binary/CDN operations проверяются native regression с mock, новая production CDN/browser приемка этим checkpoint не заявляется. Новый organizer UI/confirmation/history и навигация архива следуют D02; D03 и конкурсные несданные черновики уже запрошены и остаются открыты. Manager/reminder/actions/results/public screens и полный QA01/REL01 остаются в первом выпуске. BE10 отдельно.

Preceding C1 Linux PG40208633691 terminal success:39 locking +1783 full/OK; General40208630839 еще in progress на момент упаковки. Это результат предыдущего bf5fc5a, не текущего C2. Новый HEAD CI фиксируется после push отдельно.0038 → backend → frontend; после C2 события сохранять readers/guards C00 1.20 и аудит, schema-down недопустим. Merge/deploy/реальных переключений/автоматического переноса или удаления Project не было.
