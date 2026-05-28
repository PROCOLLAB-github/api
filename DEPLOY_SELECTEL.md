# PROCOLLAB: подготовка деплоя на Selectel

Документ описывает безопасный production-like запуск backend `procollab_api` и frontend `procollab_front`.
Готового сервера пока нет: команды ниже не выполняются автоматически и требуют ручного запуска администратором.

Короткий пошаговый checklist для первого запуска на Selectel: [`SELECTEL_FIRST_RUN_CHECKLIST.md`](SELECTEL_FIRST_RUN_CHECKLIST.md).

## 1. Требования к серверу

- Ubuntu/Debian Linux.
- Python 3.11.
- Node.js 18.x для сборки Angular frontend.
- PostgreSQL 15/16 или Selectel Managed PostgreSQL.
- Redis 7/8 для Celery, cache и Channels.
- Nginx с HTTPS.
- systemd или Docker Compose. Текущий backend уже имеет Dockerfile/compose; frontend можно раздавать как static build через Nginx.

## 2. Backend env

Скопировать шаблон:

```bash
cp .env.production.example .env
chmod 600 .env
```

Обязательные production-переменные:

```env
DEBUG=False
DJANGO_SECRET_KEY=
ALLOWED_HOSTS=api.example.com
CSRF_TRUSTED_ORIGINS=https://api.example.com,https://app.example.com
CORS_ALLOWED_ORIGINS=https://app.example.com
CORS_ALLOW_ALL_ORIGINS=False
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=0
FRONTEND_URL=https://app.example.com
SITE_URL=https://app.example.com
```

PostgreSQL можно задать через `DATABASE_URL`:

```env
DATABASE_URL=postgres://user:password@host:5432/dbname
```

или через `DB_*`:

```env
DB_ENGINE=django.db.backends.postgresql
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=5432
```

Старые переменные `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_HOST`, `DATABASE_PORT` пока поддерживаются для совместимости с существующими compose/CI.

Redis/Celery/Channels:

```env
REDIS_URL=redis://redis:6379/0
REDIS_CACHE_URL=redis://redis:6379/1
CHANNEL_REDIS_URL=redis://redis:6379/2
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
CELERY_LOG_LEVEL=info
```

Email:

```env
EMAIL_BACKEND=anymail.backends.unisender_go.EmailBackend
EMAIL_USER=procollab_info@procollab.ru
DEFAULT_FROM_EMAIL=PROCOLLAB <procollab_info@procollab.ru>
UNISENDER_GO_API_KEY=
UNISENDER_GO_API_URL=https://go1.unisender.ru/ru/transactional/api/v1/
VERIFY_EMAIL_REDIRECT_URL=https://procollab.pro/auth/verification/
PASSWORD_RESET_FRONTEND_URL=https://procollab.pro/auth/reset_password/
```

`EMAIL_USER` / `DEFAULT_FROM_EMAIL` должен быть подтвержденным отправителем в Unisender Go. Реальный `UNISENDER_GO_API_KEY` хранится только в `.env`. Проверка отправки:

```bash
python manage.py send_test_email your@email.example --template registration
```

Local dev может использовать:

```env
DEBUG=True
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
FILE_STORAGE=local
```

## 3. Storage

Переключатель storage явный:

```env
FILE_STORAGE=local
```

или:

```env
FILE_STORAGE=selectel
SELECTEL_ACCOUNT_ID=
SELECTEL_CONTAINER_NAME=
SELECTEL_CONTAINER_USERNAME=
SELECTEL_CONTAINER_PASSWORD=
```

Вариант A, persistent volume:

- Подходит для MVP и pre-prod.
- Использовать `FILE_STORAGE=local`.
- `MEDIA_ROOT` находится в backend `media/`.
- Нужен регулярный backup `media/`.
- Nginx может раздавать media через `alias`, если файлы публичные. Приватные документы нельзя раздавать напрямую без проверки прав.

Вариант B, Selectel Object Storage / Swift:

- Предпочтительнее для production.
- Использовать `FILE_STORAGE=selectel`.
- Загруженные файлы будут сохраняться через существующий `SelectelSwiftStorage`.
- Проверить права контейнера, lifecycle/backup и публичность URL.

## 4. Первый запуск backend

Через venv:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install poetry==1.2.2
poetry install
python manage.py check --deploy
python manage.py migrate
python manage.py collectstatic --no-input
python manage.py createsuperuser
daphne -b 127.0.0.1 -p 8000 procollab.asgi:application
```

Через Docker image:

```bash
docker compose -f docker-compose.prod-ci.yml config
docker compose -f docker-compose.prod-ci.yml pull web celerys
docker compose -f docker-compose.prod-ci.yml run --rm web python manage.py migrate
docker compose -f docker-compose.prod-ci.yml up -d
```

Если PostgreSQL размещен на этом же сервере, создать БД и пользователя вручную:

```bash
sudo -u postgres psql
CREATE USER procollab WITH PASSWORD 'change-me';
CREATE DATABASE procollab OWNER procollab;
ALTER ROLE procollab SET client_encoding TO 'utf8';
ALTER ROLE procollab SET default_transaction_isolation TO 'read committed';
ALTER ROLE procollab SET timezone TO 'Europe/Moscow';
```

## 5. Celery

Текущий `scripts/celery.sh` запускает worker и beat в одном процессе:

```bash
celery -A procollab worker --beat --loglevel="${CELERY_LOG_LEVEL:-info}"
```

Это допустимо для MVP/pre-prod, но рискованно для production:

- при нескольких worker будет несколько beat-планировщиков;
- перезапуск worker перезапускает beat;
- сложнее мониторить задачи отдельно.

Production-рекомендация: разделить systemd/compose services на `celery worker` и `celery beat` перед масштабированием.

Минимальные команды:

```bash
celery -A procollab worker --loglevel=info
celery -A procollab beat --scheduler django_celery_beat.schedulers:DatabaseScheduler --loglevel=info
```

## 6. Frontend build

В frontend-репозитории:

```bash
npm ci
npm run build:social:prod
```

Production build лежит в:

```text
dist/social_platform
```

Runtime env задается файлом:

```text
dist/social_platform/assets/env.js
```

Пример для единого домена frontend + backend proxy:

```js
window.__PROCOLLAB_CONFIG__ = {
  apiUrl: "/api",
  skillsApiUrl: "/skills-api",
  websocketUrl: "",
  sentryDns: "",
};
```

Пример для отдельных доменов:

```js
window.__PROCOLLAB_CONFIG__ = {
  apiUrl: "https://api.example.com",
  skillsApiUrl: "https://skills-api.example.com",
  websocketUrl: "wss://api.example.com/ws",
  sentryDns: "",
};
```

## 7. Nginx example

Для Angular routes нужен fallback:

```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

Пример единого frontend-домена с backend proxy:

```nginx
server {
    listen 80;
    server_name app.example.com;

    root /var/www/procollab/social_platform;
    index index.html;
    client_max_body_size 100M;

    location = /assets/env.js {
        try_files $uri =404;
        add_header Cache-Control "no-store";
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Если API остается на отдельном домене, в `assets/env.js` указать полный `apiUrl`, а в Nginx frontend оставить только static/fallback.

## 8. Static и media

Static:

```bash
python manage.py collectstatic --no-input
```

Backend static можно раздавать через WhiteNoise или Nginx. Для высокой нагрузки лучше Nginx.

Media:

- `FILE_STORAGE=local`: нужен persistent volume и backup.
- `FILE_STORAGE=selectel`: файлы уходят в Selectel storage.
- При переносе с SQLite не забыть переносить `media/` отдельно, потому что dumpdata переносит только ссылки в БД.

## 9. SQLite -> PostgreSQL

Не выполнять перенос без отдельного подтверждения.

1. Остановить запись в старую SQLite БД.
2. Сделать backup:

```bash
cp db.sqlite3 backups/db.sqlite3.$(date +%Y%m%d%H%M%S)
tar -czf backups/media.$(date +%Y%m%d%H%M%S).tar.gz media/
```

3. Выгрузить данные:

```bash
DEBUG=True python manage.py dumpdata \
  --exclude contenttypes \
  --exclude auth.Permission \
  --exclude admin.LogEntry \
  --exclude sessions.Session \
  --natural-foreign \
  --natural-primary \
  --indent 2 > backups/sqlite_dump.json
```

4. Настроить `.env` на PostgreSQL.
5. Применить миграции:

```bash
python manage.py migrate
```

6. Загрузить данные:

```bash
python manage.py loaddata backups/sqlite_dump.json
```

7. Перенести `media/`, если используется `FILE_STORAGE=local`.
8. Проверить целостность:

```bash
python manage.py check
python manage.py showmigrations
python manage.py shell
```

Если локальные данные нужны только как demo-data, предпочтительнее использовать `core/management/commands/seed_demo_data.py` или отдельные fixtures вместо переноса всей SQLite базы.

## 10. Smoke checks

После деплоя проверить вручную:

- `/admin/login/` открывается.
- Логин пользователя.
- `/office/program` открывается.
- Создание черновика кейс-чемпионата.
- Редактирование черновика.
- Отправка на модерацию.
- Админская модерация.
- Регистрация участника.
- Загрузка файла.
- Email notification через Unisender Go.
- Celery worker отвечает на `celery -A procollab inspect ping`.
- Beat-задачи не дублируются.
- Static assets грузятся.
- Media files доступны по выбранному storage-сценарию.
- WebSocket `/ws/chat/` подключается через Nginx.

## 11. Security checklist

- `DEBUG=False`.
- `DJANGO_SECRET_KEY` только из env.
- `ALLOWED_HOSTS` содержит только реальные hostnames.
- `CSRF_TRUSTED_ORIGINS` содержит HTTPS frontend/backend origins.
- `CORS_ALLOWED_ORIGINS` содержит только frontend origins.
- `CORS_ALLOW_ALL_ORIGINS=False`.
- `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")`.
- `SECURE_SSL_REDIRECT=True`, если HTTPS завершается на Nginx.
- `SECURE_HSTS_SECONDS` включать только после проверки HTTPS на реальном домене.
- Cookies secure при `DEBUG=False`.
- Секреты не попадают в git, logs и error reports.
- Приватные verification/certificate/user documents не раздаются напрямую без проверки прав.
