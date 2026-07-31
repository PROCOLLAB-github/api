# Backend React-dev autodeploy

<!-- Roadmap: DEV-075 -->

## Назначение

DEV-075 автоматически доставляет backend в отдельный React-dev контур после
успешного PostgreSQL CI:

```text
push master → Backend PostgreSQL CI → Backend React-dev deploy
```

Deploy запускается только для успешного `push` в `master`. Проверка pull request
не запускает deploy, поэтому непроверенный или еще не объединенный commit не
попадает на сервер.

## Exact SHA

Workflow получает SHA из завершившегося `Backend PostgreSQL CI`, проверяет формат
из 40 lowercase hexadecimal символов и выполняет checkout именно этого commit.
Перед SSH фактический `git rev-parse HEAD` сравнивается с SHA успешного CI. На
сервер передаются только проверенные SHA и GitHub Actions run ID.

Серверный script выполняет `git fetch origin master --prune`, проверяет наличие
commit и его принадлежность текущему `origin/master`. `git pull` не используется.
Если `origin/master` уже указывает на более новый commit, deploy признается
устаревшим и завершается без изменения code или containers: следующий workflow
доставит актуальную версию.

## GitHub Secrets и SSH

Workflow использует только следующие GitHub Secrets:

- `REACT_DEV_SSH_HOST`;
- `REACT_DEV_SSH_PORT`;
- `REACT_DEV_SSH_USER`;
- `REACT_DEV_SSH_PRIVATE_KEY`;
- `REACT_DEV_SSH_KNOWN_HOSTS`.

Значения не хранятся в репозитории и не передаются в `.env`. Private key и
`known_hosts` записываются во временный `~/.ssh` runner с правами `600`;
Windows CRLF удаляются. SSH использует `BatchMode`, `IdentitiesOnly`,
`StrictHostKeyChecking=yes` и отдельный `UserKnownHostsFile`.

`REACT_DEV_SSH_KNOWN_HOSTS` должен содержать заранее проверенный pinned host key.
Workflow намеренно не использует `ssh-keyscan` и не принимает новый ключ
автоматически.

## Изоляция

Единственный разрешенный repository:

```text
/root/api-react-dev
```

Script проверяет точный `realpath`, наличие `.git` и origin
`PROCOLLAB-github/api`. Старый backend в `/root/api`, production containers,
production database, nginx и production URL не используются.

Tracked staged/unstaged изменения блокируют deploy. Untracked и ignored файлы не
удаляются, `git clean` не выполняется, серверный `.env` сохраняется.

## Docker Compose

Repository `docker-compose.yml` является legacy и запрещен для автодеплоя.
Script находит уже работающий `web` container по labels:

- `com.docker.compose.project=api-react`;
- `com.docker.compose.service=web`.

Фактические Compose services `web`, `celerys` и `redis` подтверждены по labels
React-dev сервера, включая `com.docker.compose.service=celerys`.

Из labels читаются Compose project, working directory и config files. Все пути
проверяются через `realpath`: working directory должен совпадать с
`/root/api-react-dev`, каждый config file должен находиться внутри этого каталога,
а legacy `docker-compose.yml` отклоняется.

Compose-команда собирается как Bash array без `eval`. До любых изменений
containers проверяется наличие точных сервисов `web`, `celerys` и `redis`. Иное
имя Celery service не угадывается: deploy завершается с явной ошибкой.

## Порядок deploy

1. Получение deployment lock через `flock`.
2. Проверка repository, origin, git state и stale deploy.
3. Сохранение предыдущих SHA, container IDs, image IDs и image references.
4. Сборка новых `web` и `celerys` images без остановки текущего backend.
5. `python manage.py check` во временном container нового `web` image без TTY
   и без доступа к stdin deploy-скрипта.
6. `python manage.py migrate --noinput` с существующим React-dev `.env`, также без TTY
   и с stdin, подключенным к `/dev/null`.
7. Пересоздание только `web` и `celerys` через `up -d --no-deps --force-recreate`.
8. Ожидание running state с ограниченным timeout.
9. Публичный HTTPS health-check.

Redis, database и nginx не пересоздаются. `docker compose down`, prune-команды и
удаление старых images не выполняются.

## Health-check

Проверяется только:

```text
https://api-react-dev.procollab.ru/programs/?limit=1
```

Успех требует одновременно:

- HTTP `200` без следования redirect;
- `Content-Type` с `application/json`;
- непустой body;
- отсутствие HTML/SPA fallback;
- корректный JSON;
- running state `web` и `celerys`.

Используются ограниченные connect/total timeout и восемь попыток с паузой.
Полный API response в лог не выводится.

## Rollback

При ошибке build, Django check или migration работающие containers не
пересоздаются; repository и image references возвращаются к предыдущему
состоянию.

Если ошибка возникла после начала пересоздания containers или на health-check,
script:

1. возвращает предыдущий code SHA;
2. возвращает предыдущие image IDs на сохраненные image references;
3. пересоздает только `web` и `celerys`;
4. повторяет ограниченный React-dev health-check;
5. сообщает результат rollback;
6. завершает deploy с ошибкой даже при успешном rollback.

Redis не затрагивается. Ошибка rollback выводится отдельно и не маскирует
исходную ошибку.

Rollback возвращает code и containers, но **не откатывает уже примененные
миграции автоматически**. Новые миграции обязаны быть backward-compatible с
предыдущим image, чтобы предыдущая версия могла работать после container
rollback.

## Concurrency

GitHub Actions использует одну общую concurrency group с
`cancel-in-progress: false`: новый deploy ждет завершения текущего. На сервере
дополнительно действует `flock` с ограниченным временем ожидания.

## Типовые ошибки

- отсутствует один из GitHub Secrets;
- pinned host key не совпадает с ключом сервера;
- SSH недоступен или запрещает key authentication;
- repository имеет tracked изменения или неверный origin;
- workflow устарел относительно текущего `origin/master`;
- Compose labels отсутствуют или указывают вне React-dev;
- сервисы называются не `web`, `celerys`, `redis`;
- build, Django check или migration завершились ошибкой;
- containers не перешли в running state;
- HTTPS endpoint вернул redirect, HTML, не-JSON или статус не `200`;
- rollback не смог восстановить containers или health-check.

Workflow не подключается к production, не изменяет старый backend и не управляет
nginx. После первого успешного deploy нужно вручную проверить React-dev API и
основной React-dev пользовательский сценарий в браузере.

После merge и первого подтвержденного deploy PR можно дополнить маркером
`Roadmap-Complete: DEV-075`. До этого используются:

```text
Roadmap-IDs: DEV-075
Roadmap-Partial: DEV-075
```
