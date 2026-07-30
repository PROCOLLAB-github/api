# Backend PostgreSQL CI

<!-- Roadmap: DEV-074 -->

Workflow `Backend PostgreSQL CI` проверяет backend на настоящем PostgreSQL, а не
на SQLite. Это важно для транзакционных блокировок, partial constraints и
поведения `select_for_update`, которые SQLite не воспроизводит.

## Когда запускается

Workflow запускается:

- для pull request в `master`;
- для push в `master`;
- вручную через `workflow_dispatch`.

Имя обязательной проверки: `Backend PostgreSQL CI`.

## Что проверяется

Job поднимает одноразовый PostgreSQL 15 и последовательно выполняет:

1. установку зависимостей из существующего `poetry.lock`;
2. preflight-проверку подключения, backend `postgresql` и поддержки
   `select_for_update`;
3. `manage.py check`;
4. `manage.py check --tag models`;
5. `makemigrations --check --dry-run`;
6. применение всех миграций;
7. Black и flake8 для `procollab/settings_ci.py`;
8. targeted-тесты блокировок и ограничений Evaluation, Application и Team;
9. полный набор backend-тестов.

Любая ошибка останавливает job. Ослабляющие флаги, пропуск ошибок и fake-миграции
не используются.

## Изоляция

`procollab.settings_ci` подключается только через переменную
`DJANGO_SETTINGS_MODULE`. Он не меняет обычный `procollab.settings` и не
используется deployment-контурами.

В CI применяются:

- одноразовая база `procollab_ci` и тестовая база `test_procollab_ci`;
- `LocMemCache` вместо Redis;
- `InMemoryChannelLayer` вместо Redis Channels;
- локальный email backend;
- синхронное выполнение Celery-задач с пробросом исключений;
- быстрый MD5 password hasher;
- отключенный React dev demo seed.

Логин и пароль PostgreSQL находятся прямо в workflow, потому что относятся
только к одноразовому service container. Это не production/dev credentials и не
секреты инфраструктуры.

## Переменные окружения

Workflow задает:

- `DJANGO_SETTINGS_MODULE=procollab.settings_ci`;
- `DJANGO_SECRET_KEY` с тестовым значением;
- `DEBUG=False`;
- `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_HOST`,
  `DATABASE_PORT`;
- `ALLOW_REACT_DEV_DEMO_SEED=False`;
- `AUTOPOSTING_ON=False`.

## Локальный запуск

Локальные проверки следует запускать только с отдельным одноразовым PostgreSQL.
Нельзя направлять `settings_ci` на существующую dev- или production-базу.

Пример для PowerShell после запуска отдельного PostgreSQL:

```powershell
$env:DJANGO_SETTINGS_MODULE = "procollab.settings_ci"
$env:DJANGO_SECRET_KEY = "local-ci-only-secret"
$env:DEBUG = "False"
$env:DATABASE_NAME = "procollab_ci"
$env:DATABASE_USER = "procollab_ci"
$env:DATABASE_PASSWORD = "procollab_ci_password"
$env:DATABASE_HOST = "127.0.0.1"
$env:DATABASE_PORT = "5432"
$env:ALLOW_REACT_DEV_DEMO_SEED = "False"
$env:AUTOPOSTING_ON = "False"

poetry run python manage.py check
poetry run python manage.py migrate --noinput
poetry run python manage.py test --verbosity 1
```

После проверки одноразовую базу или контейнер нужно удалить.

## Типовые ошибки

- `connection refused`: PostgreSQL еще не готов или указан неверный порт.
- `password authentication failed`: переменные пользователя и пароля не
  совпадают с настройками одноразового PostgreSQL.
- `database does not exist`: не создана исходная база `procollab_ci`.
- `makemigrations --check` предлагает миграцию: модели и миграции расходятся.
- preflight сообщает не `postgresql`: выбран неверный settings module или
  переопределены параметры базы.
- тест блокировок зависает или завершается по timeout: следует проверить порядок
  транзакционных блокировок и конкурентные изменения, а не отключать тест.

Workflow не выполняет deployment, не подключается к dev/production-сервисам и не
запускает команды на существующих базах.
