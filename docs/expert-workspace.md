# Эксперты программы и личное оценивание

Организатор приглашает экспертов по email и назначает им сданные проекты. После
явного принятия приглашения эксперт видит программу и свои назначения в кабинете.
Основание доступа — `Expert.programs`, независимо от основной роли пользователя.
Организатор не получает право оценивать автоматически.

## Контракт

Все organizer endpoints ниже требуют менеджера **конкретной** программы:

| Метод и путь относительно `/programs/{id}/management/` | Назначение |
| --- | --- |
| GET `experts/` | Состав, приглашения, нагрузка, N, нехватка и revision |
| POST `experts/` | Пригласить `{email}` |
| POST `expert-invitations/{id}/resend/` | Новая ссылка, прежняя недействительна |
| POST `expert-invitations/{id}/revoke/` | Отозвать непринятое приглашение |
| GET `experts/{expert_id}/assignments/` | Проекты с assigned/protected/own_team |
| PUT `experts/{expert_id}/assignments/` | Заменить набор `{revision, project_ids}` |
| POST `expert-allocation/` | Предпросмотр `{expert_ids, project_ids?}` |
| POST `expert-allocation/apply/` | Применить подписанный `{plan_token}` |
| POST `evaluators/` | Предпросмотр `{required_evaluators}` |
| PUT `evaluators/` | Подтвердить `{required_evaluators, revision}` |

`GET /evaluation/programs/` возвращает только программы пользователя, его счётчики
assigned/completed/remaining и действующие приглашения на его email.
`POST /evaluation/own-invitations/{id}/accept/` явно принимает своё приглашение.

`GET /evaluation/invitations/{token}/` возвращает контекст ссылки, фиксированный
email, account_exists, login_email и matches_account. Записей при GET нет.
`POST .../{token}/accept/` требует входа в активный аккаунт с этим email.
`POST .../{token}/register/` принимает first_name, last_name, password,
repeat_password, accept_policy, accept_age и атомарно создаёт аккаунт, членство
и acceptance; возвращает access/refresh/program_id. Email задаётся приглашением.

Ошибки: 400 — невалидный ввод, 403 — нет прав/другая почта, 404 — нет объекта,
409 — дубликат, устаревший revision/plan или защищённая оценка, 410 — ссылка
истекла/отозвана. Повторное acceptance тем же аккаунтом безопасно.

## Правила

- Pending не является экспертом и не участвует в распределении.
- Новые назначения — только принявшим приглашение активным экспертам, на сданные
  проекты своей программы; собственная команда исключена.
- Любая сохранённая оценка защищает назначение от удаления, включая старые
  неполные наборы. Участие в команде, назначения и оценки входят в revision.
- Автораспределение заполняет дефицит до N, сохраняя существующие назначения,
  и балансирует незавершённую нагрузку. Предпросмотр ничего не записывает.
  Нехватка кандидатов блокирует применение; план действует 15 минут.
- Все новые записи организатора и сохранение оценок используют одну блокировку
  строки программы. Конкурирующая запись отклоняется целиком с 409.
- N — минимум полных оценок, а не максимум. Изменять его можно в любое время;
  готовность пересчитывается, оценки и лишние назначения сохраняются.
- Управляемая форма оценки сохраняется целиком: целые баллы и Да/нет обязательны,
  комментарий необязателен. 0 и False — допустимые ответы. Дедлайн, назначение,
  сданное решение и запрет оценки своей команды проверяются сервером.
- Первая сохранённая оценка продолжает блокировать критерии.

## Совместимость и rollout

Добавлены `PartnerProgram.required_evaluators`, `ExpertInvitation` и nullable
`CustomUser.birthday`: migrations partner_programs.0022, project_rates.0004,
users.0065. Обычная регистрация продолжает требовать дату рождения; обычный
профиль не может удалить её. Только новый приглашённый эксперт создаётся без даты,
без фиктивного значения, повторного подтверждения email и обязательного onboarding.

Legacy rating endpoints/payload и open mode на backend сохраняются. Явное
приглашение, ручное назначение, применение распределения или подтверждение N
включает управляемый режим программы; назначения за историческими оценками
восстанавливаются без изменения самих оценок. `max_project_rates` остаётся
legacy максимумом. Новый Angular запрашивает `assigned_only=1`: он показывает
свои назначения, поэтому организатору нужно распределить проекты существующим
экспертам перед использованием нового кабинета.

Сначала backend/migrations, затем Angular. DEV использует существующее отдельное
migration connection из Deploy Dev; runtime остаётся под application role.
Откат UI возможен независимо; откат nullable birthday после создания приглашённых
аккаунтов требует отдельной обработки данных, обратную миграцию вслепую не запускать.

## Письма

Ссылка имеет случайный bearer token, в БД хранится SHA-256 digest. Срок — 7 дней;
повторная отправка заменяет token. `EXPERT_WORKSPACE_FRONTEND_URL` задаёт разрешённый
frontend origin (DEV: `https://dev.procollab.ru`) для Web и Celery. Нельзя передавать
произвольный return URL. `queued/sent/failed` описывает передачу почтовому backend,
а не подтверждение доставки в inbox. Используется существующий Celery/mail provider.

В `/auth/reset_password/` можно передать `expert_invitation_token`. Для действующей
ссылки, соответствующей email, reset email ведёт на `/expert-password-reset/` настроенного frontend с контекстом
приглашения. После смены пароля — вход и отдельное acceptance. Общий reset не менялся.
Private ответы не кешируются; invitation token скрывается application HTTP logger.

На DEV Nginx направляет `/evaluation/` в API. `/expert-invitation/` и
`/expert-password-reset/` остаются SPA routes; отдельный reset route обходит
server-side `/auth/`, который на совмещённом DEV-host принадлежит API.

## Проверяемые требования

AC1 invite/resend/revoke, scope, duplicate и доставка; AC2 signup без даты с сохранением
обычной регистрации; AC3 login, wrong account, expiry/replay/reset и гонки; AC4 manual
scope/своя команда/защищённые оценки; AC5 preview/balance/stale apply; AC6 N и полная
оценка; AC7 личные программы и роли; AC8 центрированные адаптивные состояния на UI;
AC9 права при прямом запросе, миграции и регресс.

Backend coverage: `project_rates.tests.test_workspace` и
`project_rates.tests.test_workspace_concurrency` (гонки требуют PostgreSQL).
UI/Figma и результаты сборки описаны в связанном Angular PR.
