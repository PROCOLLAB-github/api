# PROCOLLAB: первый ручной запуск на Selectel

Этот чеклист нужен для первого MVP/pre-prod запуска. Он не предполагает автоматический деплой, пуш или коммит. Реальные секреты не хранить в репозитории и не вставлять в чат.

## 1. Что создать в Selectel

- Cloud server / VM: 2 vCPU, 6 GB RAM, 80 GB SSD.
- Network: public network `/29`, 1 public IPv4.
- OS: Ubuntu 22.04 LTS или Ubuntu 24.04 LTS.
- Services on the same server for MVP: PostgreSQL, Redis, Nginx, backend, Celery worker/beat, frontend static build.
- File storage for first run: `FILE_STORAGE=local`, media on persistent disk with backup.
- Email: existing Anymail Unisender Go backend.

## 2. Ports and access

Open only the minimum ports:

```text
22/tcp   SSH
80/tcp   HTTP, temporary IP run and later ACME challenge
443/tcp  HTTPS after domain/TLS is configured
```

Keep PostgreSQL `5432` and Redis `6379` closed from the public internet. They should listen on localhost or private interface only.

Create a non-root deploy user:

```bash
adduser deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
```

Add the public SSH key to `/home/deploy/.ssh/authorized_keys`, then disable password SSH login after confirming key login works.

## 3. Base packages

```bash
sudo apt update
sudo apt install -y \
  git curl ufw nginx postgresql postgresql-contrib redis-server \
  python3.11 python3.11-venv python3-pip \
  build-essential libcairo2 libpango-1.0-0 libpangoft2-1.0-0 \
  libgdk-pixbuf2.0-0 shared-mime-info
```

Install Node.js 18.x for Angular build, or build frontend locally/CI and upload `dist`.

## 4. PostgreSQL

Create the DB and user manually:

```bash
sudo -u postgres psql
CREATE USER procollab WITH PASSWORD '<generate-strong-password>';
CREATE DATABASE procollab OWNER procollab;
ALTER ROLE procollab SET client_encoding TO 'utf8';
ALTER ROLE procollab SET default_transaction_isolation TO 'read committed';
ALTER ROLE procollab SET timezone TO 'Europe/Moscow';
\q
```

Production-like backend env must use PostgreSQL, never SQLite:

```env
DB_ENGINE=django.db.backends.postgresql
DB_NAME=procollab
DB_USER=procollab
DB_PASSWORD=<secret>
DB_HOST=127.0.0.1
DB_PORT=5432
```

`DATABASE_URL=postgres://...` is also supported, but use either `DATABASE_URL` or `DB_*`, not both.

## 5. Redis and Celery

For the first single-server run:

```env
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_CACHE_URL=redis://127.0.0.1:6379/1
CHANNEL_REDIS_URL=redis://127.0.0.1:6379/2
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
CELERY_LOG_LEVEL=info
```

MVP can use the existing combined worker/beat command, but for production prefer separate services:

```bash
celery -A procollab worker --loglevel=info
celery -A procollab beat --scheduler django_celery_beat.schedulers:DatabaseScheduler --loglevel=info
```

## 6. Backend env for temporary IP run

Until there is a domain and TLS, run by public IP with explicit HTTP origins:

```env
DEBUG=False
DJANGO_SECRET_KEY=<generate-new-secret>
ALLOWED_HOSTS=<PUBLIC_IP>
CSRF_TRUSTED_ORIGINS=http://<PUBLIC_IP>
CORS_ALLOWED_ORIGINS=http://<PUBLIC_IP>
CORS_ALLOW_ALL_ORIGINS=False
FRONTEND_URL=http://<PUBLIC_IP>
SITE_URL=http://<PUBLIC_IP>
SECURE_SSL_REDIRECT=False
SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
```

After domain and HTTPS are ready, replace IP values with final hosts/origins, set HTTPS URLs, then enable `SECURE_SSL_REDIRECT=True`. Enable HSTS only after HTTPS is verified.

## 7. Storage and email

First run storage:

```env
FILE_STORAGE=local
LOCAL_MEDIA_BASE_URL=http://<PUBLIC_IP>/media/
```

Create a persistent media directory and backup it regularly. Do not serve private personal documents directly through Nginx unless access control requirements are confirmed.

Production email:

```env
EMAIL_BACKEND=anymail.backends.unisender_go.EmailBackend
DEFAULT_FROM_EMAIL=<verified-sender>
EMAIL_USER=<verified-sender>
UNISENDER_GO_API_KEY=<secret>
UNISENDER_GO_API_URL=https://go1.unisender.ru/ru/transactional/api/v1/
VERIFY_EMAIL_REDIRECT_URL=https://procollab.pro/auth/verification/
PASSWORD_RESET_FRONTEND_URL=https://procollab.pro/auth/reset_password/
```

Use the verified sender from Unisender Go, for example `PROCOLLAB <procollab_info@procollab.ru>`. Do not put the API key into Git. Check delivery before the demo:

```bash
docker compose --profile legacy exec web python manage.py send_test_email <your-email> --template registration
```

## 8. Frontend runtime config

Build frontend:

```bash
npm ci
npm run build:prod
```

For same-origin Nginx proxy, keep `assets/env.js` like this:

```js
window.__PROCOLLAB_CONFIG__ = {
  apiUrl: "/api",
  skillsApiUrl: "/skills-api",
  websocketUrl: "",
  sentryDns: "",
};
```

For a temporary IP with separate backend origin, use explicit URLs:

```js
window.__PROCOLLAB_CONFIG__ = {
  apiUrl: "http://<PUBLIC_IP>/api",
  skillsApiUrl: "http://<PUBLIC_IP>/skills-api",
  websocketUrl: "ws://<PUBLIC_IP>/ws",
  sentryDns: "",
};
```

## 9. Nginx

Use the frontend example from `procollab_front/deploy/nginx/social_platform.conf.example`.

Required behavior:

- Angular routes fallback with `try_files $uri $uri/ /index.html`.
- `/api/` proxies to backend.
- `/ws/` proxies WebSocket connections.
- `/assets/env.js` is not aggressively cached.
- `client_max_body_size` is high enough for uploads.

## 10. First backend run

```bash
cd /srv/procollab/procollab_api
cp .env.production.example .env
chmod 600 .env
# fill .env manually
python manage.py check --deploy
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

Start services with systemd or another supervisor:

- backend ASGI: `daphne -b 127.0.0.1 -p 8000 procollab.asgi:application`
- Celery worker
- Celery beat
- Nginx

## 11. Smoke checks

- Frontend opens by IP or domain.
- Login works.
- `/office/program` opens.
- Program draft can be created and edited.
- Program can be submitted to moderation.
- Admin moderation opens for staff user.
- Participant registration works.
- File upload works.
- Static files load.
- Media files load according to selected storage mode.
- Email notification is sent through Unisender Go.
- Celery worker is alive: `celery -A procollab inspect ping`.
- WebSocket endpoint connects through Nginx.

## 12. Data needed from project owner

Prepare these values outside the repository:

- Public IP.
- SSH user.
- SSH private key path.
- Domain, when available.
- Backend host.
- Frontend host.
- `DJANGO_SECRET_KEY`.
- PostgreSQL DB name, user, password.
- `REDIS_URL`.
- `UNISENDER_GO_API_KEY`.
- `DEFAULT_FROM_EMAIL`.
- `FILE_STORAGE` mode.
- Selectel storage credentials, only if switching to `FILE_STORAGE=selectel`.
- `FRONTEND_URL`.
- `SITE_URL`.
- `ALLOWED_HOSTS`.
- `CSRF_TRUSTED_ORIGINS`.
- `CORS_ALLOWED_ORIGINS`.

Do not send real secret values in chat. Put them only into the server `.env` or a secret manager.
