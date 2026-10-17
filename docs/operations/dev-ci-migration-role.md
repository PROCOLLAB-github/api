# DEV migration connection в CI

## Задача и границы

Deploy Dev применял миграции под runtime login из `.env`, что приводило к
`must be owner of table`. Теперь отдельные credentials используются только внутри
одноразового migration container. Web/Celery остаются под `procollab_api_dev`.
API, UI, модели, numbered migrations, PROD workflow и production secrets не меняются.

Под migration-role здесь понимается существующий владелец `procollab_api` в отдельном
CI-подключении. Новый PostgreSQL login не создаётся. Одноразовая подготовка ниже
использует временное членство DEV role → migration role с последующим отзывом.
CI жёстко ограничивает database name и runtime user; secrets PROD workflow не читаются.

## Согласованная схема DEV / PROD, 18.10.2026

Пользователь выбрал `procollab_api` для миграций обоих контуров, сохранив
существующие подключения web/Celery. [Read-only preflight обоих контуров](https://github.com/PROCOLLAB-github/api/actions/runs/39072746180)
проверил actual connection identity, ownership и role flags в READ ONLY transaction:

| Контур | Фактическая БД | Web/Celery сейчас | Миграции сейчас | Целевая роль миграций |
| --- | --- | --- | --- | --- |
| DEV | `procollab_db_dev` | `procollab_api_dev` | `procollab_api_dev` | `procollab_api` |
| PROD | `procollab_db_test` | `procollab_api` | `procollab_api` | `procollab_api` — уже используется |

Название `procollab_db_test` здесь относится к фактическому deployed PROD:
контур установлен по серверному checkout и работающему production image, а не по имени БД.
Одинаковый `pg_control_system().system_identifier` подтвердил общий PostgreSQL-кластер.
Следовательно, `procollab_api` — одна существующая cluster-wide роль, а не два
независимых login с одинаковым названием. Её пароль не ротируется в рамках задачи.

В PROD все 107 tables / 100 sequences принадлежат `procollab_api`; не принадлежащих
ей relations нет. Для выбранной роли изменения PROD workflow, ownership и grants
не требуются. Существующий PROD runtime тоже использует эту роль; разделение
runtime/migration прав в PROD не заявляется и в scope не входит.

В DEV остаётся одноразовая подготовка university table/sequence, описанная ниже.
Секрет `DEV_MIGRATION_DATABASE_PASSWORD` добавлен пользователем; наличие подтверждено
по metadata, значение не читалось и live owner authentication пока не проверена.

## Фактическое состояние до активации, 17.10.2026

[Read-only inspection](https://github.com/PROCOLLAB-github/api/actions/runs/39059401759):

- Runtime image: `c78078c26acb6585867b0b5c1a9be93abd76d45b-5ac944d0794f`.
- PostgreSQL 14.24; database `procollab_db_dev`; runtime `procollab_api_dev`.
- 95 tables / 89 sequences принадлежат `procollab_api`.
- `users_university` / `users_university_id_seq` принадлежат runtime login.
- Оба login не имеют SUPERUSER / CREATEDB / CREATEROLE / REPLICATION / BYPASSRLS.
- У владельца уже есть default ACL для runtime на новые tables/sequences/functions.
- Отдельных DEV migration secrets до задачи не было.

## Проверяемые требования

| AC | Наблюдаемый результат |
| --- | --- |
| M1 | Только refs/heads/dev; database строго procollab_db_dev |
| M2 | Missing secret отклоняется до SSH, без fallback на application/production secrets |
| M3 | Migration credentials не записываются в .env, CLI argv, web/Celery environment |
| M4 | Неадминистративная migration-role может изменять существующие DEV relations |
| M5 | Новые tables/sequences доступны runtime для штатных CRUD/sequence операций |
| M6 | Mixed ownership отклоняется до DDL/default-privilege изменений |
| M7 | После migrate обычное подключение проходит migrate --check |
| M8 | Конкурирующие DEV deploy выполняются последовательно; PROD не затронут |

## CI secrets и последовательность

GitHub Environment `dev`, deployment branch policy — только branch `dev`, без
manual reviewers. В нём используются отдельные secrets:

- `DEV_MIGRATION_DATABASE_USER`: `procollab_api`.
- `DEV_MIGRATION_DATABASE_PASSWORD`: актуальный пароль этого login из Selectel.

Environment variable `DEV_SSH_HOST_KEY_SHA256` содержит публичный ED25519 fingerprint
DEV-сервера, проверенный отдельной read-only inspection. Это не пароль. При ротации
host key сначала независимо проверяется новый публичный ключ, затем обновляется
эта переменная; отключать host verification нельзя.

Пароль добавляется владельцем через GitHub Environment secrets; в чат, issue, PR
или repository file его передавать нельзя. GitHub API не позволяет прочитать
ранее сохранённое значение секрета. Обычные DEV_DATABASE_* остаются без изменения.

Перед SSH runner проверяет credentials и создаёт base64 JSON, регистрирует его
через [add-mask](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#masking-a-value-in-a-log)
и передаёт как step output в stdin helper. Base64 обеспечивает только безопасный
transport, не шифрование. В payload нет host/database overrides.

`scripts/dev_ci_ssh.cjs` использует pinned `ssh2@1.16.0`, проверяет host fingerprint
и запускает только фиксированный `bash -se`. Весь deploy script передаётся через
SSH stdin: secret-bearing script не попадает в argv удалённого shell и не
записывается во временный файл. Старый SSH action заменён только в DEV workflow.
Скрипт передаётся единым Bash-блоком с stdin `/dev/null`: Bash разбирает его целиком
до выполнения, поэтому `docker exec` не может поглотить последующие checks из SSH stdin.
Явные heredoc payload/Python продолжают работать. Regression tests запускают настоящий
Bash через loopback SSH: stdin-consuming child не пропускает завершающие checks,
а ошибка последующего check завершает deployment с ошибкой.

Helper проверяет фактическую identity, schema CREATE/USAGE, отсутствие admin flags,
ownership tables/sequences и текущие runtime grants внутри READ ONLY transaction.
Затем настраивает additive default privileges, выполняет migrate, проверяет отсутствие
pending migrations и доступ runtime к relations. Отдельный container выполняет
`manage.py migrate --check` с обычной `.env` до перезапуска web/Celery.

## Одноразовая подготовка ownership

До merge/активации нужно выполнить [dev-migration-role-university-owner.sql](dev-migration-role-university-owner.sql)
только в `procollab_db_dev`. Транзакция переносит ровно university table и проверяет
её owned sequence, сохраняя runtime privileges и данные. Это не повторяемый шаг CI.

На фактической PostgreSQL 14 отдельный администратор не обязателен:
[GRANT PostgreSQL 14](https://www.postgresql.org/docs/14/sql-grant.html) разрешает
session_user выдавать членство в собственной роли. Это отдельно проверено на
[disposable PostgreSQL 14.24](https://github.com/PROCOLLAB-github/api/actions/runs/39075480886).
Поведение PostgreSQL 18 отличается; helper отказывается применять эту процедуру к другим major versions.

`scripts/dev_ci_prepare_owner.py` использует два существующих login:

1. Спрашивает только скрытый пароль `procollab_api`; runtime credentials берёт из environment контейнера.
2. Подключается к DEV под `procollab_api_dev` и `procollab_api`, проверяет обе identity и PostgreSQL 14.
3. При необходимости временно делает `GRANT procollab_api_dev TO procollab_api`.
4. Под `procollab_api` выполняет проверенный SQL смены владельца и runtime grants.
5. В `finally` отзывает только добавленное членство; существующее членство не удаляет.

Направление grant — DEV role → migration role. Runtime DEV не становится членом
PROD owner-role. Членство действует на кластер, поэтому временно расширяются права
общей `procollab_api` на DEV; PROD objects и grants не меняются. Advisory lock не
позволяет двум экземплярам helper конкурировать. Ошибки SQL откатывают незавершённую
транзакцию перед отзывом членства; SIGINT/SIGTERM/SIGHUP выполняют cleanup.
При принудительном убийстве процесса или недоступности БД cleanup нельзя гарантировать:
перед продолжением проверить членство и при необходимости под `procollab_api_dev`
выполнить `REVOKE procollab_api_dev FROM procollab_api`.

Для самого SQL нужны права фактического владельца и возможность передать ownership целевой роли;
server root или обычного GRANT ALL недостаточно для этого
([PostgreSQL 14 ALTER TABLE](https://www.postgresql.org/docs/14/sql-altertable.html)).
При недостатке прав или неожиданной identity транзакция откатится целиком.
Mass REASSIGN OWNED не используется: он затрагивает также shared database/tablespace
objects ([PostgreSQL](https://www.postgresql.org/docs/16/role-removal.html)).

Нельзя мержить fail-closed workflow до добавления пароля и нормализации ownership:
иначе следующий DEV deploy ожидаемо остановится. Старая версия приложения при
ошибке preflight остаётся в работающих контейнерах.

## Проверка

`python -m unittest discover -s scripts/tests -p test_dev_ci_migrate.py -v` запускает
credentials tests. Реальные PostgreSQL tests требуют disposable instance и
`RUN_DEV_MIGRATION_PG_TESTS=1`; они отказываются заменять существующую тестовую БД
или роли. Матрица GitHub CI покрывает PostgreSQL 14 (версия DEV) и 18.

`node --test scripts/tests/test_dev_ci_ssh.cjs` с установленным `ssh2@1.16.0`
проверяет реальное loopback SSH соединение: stdin вместо argv, отказ чужому host
key до authentication, missing config, controlled remote failure и timeout.

Проверяются исходный ownership failure, успешные ALTER/CREATE migrations, runtime
CRUD/sequence на новой таблице, сохранность `.env`, idempotency, READ ONLY check,
mixed ownership fail-before-write, отказ admin credentials, special characters
в пароле и отсутствие пароля/traceback в сообщении об ошибке.

Фактические результаты и ограничения активации фиксируются в PR description.
Без настоящих migration credentials live DDL проверка не объявляется выполненной.
