# Пилот «Сознание права»

Изолированное демонстрационное окружение до подтверждения клиента. Квиз не входит.
Пакет не меняет DNS, nginx хоста, существующий dev/prod или их данные.

`pilot.procollab.ru` уже имеет A `5.188.81.217`; NS домена — REG.RU.
HTTPS пока возвращает обычный Procollab.

## Существующий сервер: сначала обследование

По выводу владельца от 11 ноября на сервере уже работают
`procollab-white-label-pilot-web-1` на `127.0.0.1:18318` и отдельный
`procollab-white-label-pilot-db-1`. Dev API использует порты 8000/8001.
Свободно 6.2 GiB диска, доступно 2.1 GiB RAM, swap отсутствует.
**На этом сервере не запускать второй compose project из этого пакета.**
Подготовленный ниже полный стек предназначен для нового окружения; его
preflight требует 8 GiB диска и 2560 MiB доступной RAM и здесь не пройдет.

Подтверждены compose `/opt/procollab-white-label-pilot/compose.yml`, образ
`procollab-white-label-pilot-base:20261109`, профиль `pilot_hosted_settings` и
bind mount `/opt/procollab-white-label-pilot/backend:/procollab`.
Uploads (`/var/lib/pilot`), static и logs используют собственные named volumes.
Сравнение исходников подтвердило 272 отличающихся и 110 отсутствующих runtime
файлов; в старой БД не применены 48 миграций текущей базы. Native registration
там отсутствует. В БД четыре существующих аккаунта не с `@example.test`; это
не основание считать их тестовыми или удалять. Прямой upgrade старой схемы не
выполняется.

Новый закрытый пилот v2: отдельные web и PostgreSQL 15, своя сеть и новые файлы
в `/opt/procollab-white-label-pilot-v2`. API слушает только `127.0.0.1:18319`,
DB не публикует порты. Старые web/DB/compose/backend/файлы остаются для отката.
Лимиты web — 768 MiB / 0.5 CPU, PG — 256 MiB / 0.25 CPU, shared_buffers 64 MiB,
max_connections 40, work_mem 1 MiB. App role не superuser. Для демо используются
локальные cache/channel layers и синхронные Celery tasks; Redis/worker не нужны.

`hosted.py` жестко проверяет hostname, root, имена/labels старых контейнеров,
сети и принадлежность routes.inc только домену pilot. Запрещает чужие ресурсы,
ссылки за пределы v2, несовпадающие artifacts и перезапись активного релиза.
Перед запуском сохраняет запас памяти 768 MiB и диска 2 GiB плюс бюджет PG.
Новые контейнеры получают повышенный OOM score, отдельные pids/log limits.
Основные процессы/настройки Docker, dev/prod, DNS и сертификаты не меняются.
Проверка dev требует работающие `api-web-1`, `api-redis-1`, `api_celery` и HTTP 200
от `dev.procollab.ru`. Сравнительный React не является зависимостью пилота:
состояние `api-react-*` не блокирует этапы и не изменяется установщиком.

## Существующий сервер: этапы v2

1. Скачать `procollab-pilot-candidate.zip` и `procollab-pilot-runtime.zip` из
   успешных workflow одного commit. Перенести их в `/root` по SSH. Runtime
   содержит compressed rootfs и public image config, без секретов.
2. Проверенным `unpack_candidate.py` распаковать только candidate ZIP в новый
   каталог. Runtime ZIP не распаковывается: rootfs читается из него потоком.
3. Из каталога `procollab-pilot` выполнить только проверку:

```sh
python3 hosted.py check --bundle . --runtime /root/procollab-pilot-runtime.zip
```

`check` читает ресурсы/конфигурацию и проверяет hashes. Он не создает контейнеры,
DB, пользователей или nginx-конфигурацию. В JSON есть план ресурсов и dev HTTP.
Далее отдельные этапы, после успешного результата предыдущего:

```sh
python3 hosted.py stage --bundle . --runtime /root/procollab-pilot-runtime.zip
python3 hosted.py switch
python3 hosted.py status
```

`stage` создает только v2, делает private backup старой БД/compose/routes,
проверяет читаемость dump через `pg_restore --list`. Импортирует проверенный
rootfs потоком (до 8 MiB/s), сохраняя запас диска; конфигурация ENV/CMD/WORKDIR
восстанавливается и проверена в CI. Новый PG запускается на закрепленном digest,
миграции/seed выполняются только в новой пустой БД `procollab_white_label_pilot_v2`.
Временный API проходит instance/native registration/login smoke. Домен остается
на старом пилоте. Новый пароль DB/Django/демо генерируется только на сервере.

`switch` сохраняет старый pilot routes.inc, применяет новый include и один
собственный maps-файл, выполняет `nginx -t` и graceful reload. Проверяет закрытый
вход, branded metadata по HTTPS и прежнюю доступность dev. При ошибке возвращает
старые routes и reload. Измененные другим оператором файлы не перезаписывает.
Ни один старый контейнер не останавливается. Все старые DB/volume остаются.

Maps-файл размещается в `/etc/nginx/sites-enabled/00-procollab-pilot-v2-maps.conf`.
Требуется существующий HTTP include `sites-enabled/*` или `sites-enabled/*.conf`;
основной `nginx.conf` не редактируется. Временные файлы скрыты от include glob.
Если bundle уже скачан, исправленный `hosted.py` можно запускать из отдельного
каталога вместе с `configure.py`, `runtime_import.py` и двумя `hosted-*.template`
из bundle. Передавать исходный bundle через `--bundle`: его manifest и runtime
остаются прежними. Все дальнейшие команды выполнять этим же `hosted.py`.

Ручной откат маршрутов:

```sh
python3 hosted.py rollback
```

Он возвращает старый пилот, не удаляя новые DB/контейнеры/данные. Каталог старого
пилота сохраняется для отката и ACME. Прежний `deploy.sh` относится к старой копии;
для v2 используется `hosted.py`. Данные входа — только на сервере в
`/opt/procollab-white-label-pilot-v2/access.txt`, root-only. В чат их не отправлять.
Это подготовка демо; нагрузка 100 участников, реальная почта и приемка клиента
проверяются отдельно.

Прямой публичный SSH из Codex Cloud в этой среде недоступен; нужен настроенный
VPN/Tailscale либо выполнение подготовленных команд владельцем в SSH-терминале.
Добавление публичного ключа само по себе не создает сетевой маршрут.

### Исправление приглашений для аккаунтов без ФИО

Новый candidate-пакет содержит `upgrade_invites.py`. Он принимает только активный
hosted-v2 на известном сервере, исходные hashes кода/зависимостей и прежний index.
Runtime image повторно не переносится: четыре проверенных Python-файла подключаются
readonly к новому web-контейнеру с тем же образом, DB, env, сетью и лимитами.
До замены сохраняются dump БД v2 и изменяемые файлы frontend. Останавливается
только прежний web v2, который сохраняется для отката; PostgreSQL, старый пилот,
dev, nginx, DNS и сертификаты не меняются. Миграции и повторный seed не запускаются.

После распаковки нового candidate в отдельный каталог:

```sh
python3 upgrade_invites.py check --bundle .
python3 upgrade_invites.py apply --bundle .
```

Перед публикацией нового index проверяются вход, точный поиск почты в программе
и отсутствие такого поиска у гостя. Затем проверяются опубликованный index и dev.
При ошибке возвращаются прежний web и frontend, сохраняя текущие данные БД.
Ручной откат: `python3 upgrade_invites.py rollback` из того же каталога.

## Сборка пакета

Workflow `Build pilot package` создает artifact `procollab-pilot-candidate`
на GitHub без деплоя/SSH и без секретов. Он берет Angular из публичного
репозитория `PROCOLLAB-github/procollab` на точном commit из
`frontend-revision.txt`, API — из проверяемого checkout. Artifact хранится
7 дней; публичность репозитория не делает демо доступным без его входа.
Это исходники и сборка для подготовки rollout, не команда установки второго
стека на существующий сервер.

В Angular checkout:

```sh
NG_CLI_ANALYTICS=false NG_BUILD_MAX_WORKERS=2 ./node_modules/.bin/ng build social_platform --configuration=pilot --output-path=/workspace/work/pilot-frontend
```

В API checkout, после tests/review и фиксации файлов в git:

```sh
python3 deploy/pilot/package.py --api /workspace/api --frontend /workspace/work/pilot-frontend/browser --target /workspace/work/procollab-pilot
```

Архив содержит API source, проверенную pilot сборку, конфигурационные шаблоны и
официальные assets. Секреты в архив не входят, создаются на целевом сервере.
Пакет отклоняет обычную сборку, направленную в основной API.

## Новый сервер: доступ и запуск полного стека

Нужен SSH-пользователь с Docker и правом проверить/установить отдельный nginx
vhost. Доступ ко всему аккаунту Selectel не обязателен. SSH key и секреты
передаются через настройки среды, а не в чат.

Распаковать архив в новый каталог, например `/srv/procollab-pilot`.
Перед стартом выполнить read-only проверку:

```sh
cd /srv/procollab-pilot
python3 preflight.py
python3 configure.py
./pilotctl check
./pilotctl build
./pilotctl start
./pilotctl status
```

`configure.py` создает новые Django/DB/демо секреты и вход `pilot` перед просмотром
стенда. Локальные `.env`, `nginx.conf`, `access.htpasswd`, `access.txt` имеют права
0600. Данные входа смотреть в `access.txt` на сервере; не публиковать и не коммитить.
Повторная конфигурация ничего не перезаписывает. Начальные пользователи:
`admin@example.test`, `organizer@example.test`, `expert@example.test`,
`leader@example.test`, `member@example.test`. Общий пароль этих синтетических
аккаунтов также находится в `access.txt`, отдельно от пароля внешнего входа.

Compose project `procollab-pilot` создает собственные network, PostgreSQL и Redis
volumes. Только gateway слушает loopback `127.0.0.1:18081`. Web/DB/Redis наружу
не публикуются. Файлы, статика и письма находятся в локальном `data`, логи — `logs`.
Загрузка файлов использует отдельный local storage, без общего Selectel bucket.
Сборка образа выполняется отдельно до запуска; `start` не запускает сборку.
При сборке на другом сервере можно перенести образ через `docker save/load`.
Лимиты контейнеров суммарно составляют 1856 MiB и 1.45 CPU; они не гарантируют
достаточность ресурсов соседним приложениям. На занятом dev-сервере этот стек
не устанавливается вместо обновления уже существующего пилота.

Daphne запускается с `--root-path /backend`, nginx сохраняет полный путь:
это сохраняет префикс в формах и ссылках Django admin. Изменение относится только
к pilot compose, обычная команда API не меняется.

## Новый сервер: HTTPS и nginx

Проверить действующий vhost и путь к сертификату для `pilot.procollab.ru`.
`host-nginx.conf.example` — готовый отдельный server block для проксирования
на loopback 18081. Сохранить прежний vhost перед заменой. Если подходящий
сертификат уже есть, использовать его подтвержденный путь; иначе выпустить
сертификат только для pilot, не меняя сертификаты соседних доменов.

Применение после проверки владельцем сервера:

```sh
sudo nginx -t
sudo systemctl reload nginx
```

Проверить: без внешнего входа и UI, и `/backend/instance/` возвращают 401.
После входа видны «Сознание права», клиентский логотип и favicon. Стандартный
адрес регистрации ведет в программу, Django admin — `/backend/admin/`.
JWT и cookie внешнего входа независимы. Cookies пилота не заменяют основную сессию.

## Почта и реальные участники

По умолчанию письма сохраняются в `data/mail`, наружу не отправляются. Signup
разрешает только `@example.test`; это подготовка демо, не прием реальных заявок.
Ссылка подтверждения берется из сохраненного письма владельцем стенда.

Сервис PROCOLLAB можно подключить после проверки действующего подтвержденного
отправителя: `PILOT_EMAIL_DELIVERY=unisender`, `EMAIL_USER` и ключ Unisender в
секретах `.env`. Перед реальным мероприятием нужны отдельная настройка режима
реальных участников, согласованные документы/доступ к данным и проверка доставки.
Не копировать общий `.env` dev/prod в пилот.

## Остановка и откат

```sh
./pilotctl stop
```

Команда останавливает только procollab-pilot, не удаляет volumes или данные.
Для отката маршрутизации вернуть сохраненный vhost pilot, выполнить `nginx -t`
и reload. Удаление БД/volumes требует отдельного решения владельца.
