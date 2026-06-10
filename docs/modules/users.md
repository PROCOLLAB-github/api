# Users

## Назначение

Users отвечает за учетные записи и профиль пользователя в Procollab:
регистрацию, подтверждение email, авторизацию, роли, публичные данные профиля,
достижения, навыки, CV, активность пользователя и связи пользователя с
проектами, программами, событиями и новостями.

## Статус модуля

Модуль рабочий, но находится в состоянии технического долга. Он исторически
содержит несколько разных доменных flow в крупных файлах `users/views.py`,
`users/serializers.py` и `users/helpers.py`.

Перед активным рефакторингом модуль требует:

- фиксации текущего поведения regression-тестами;
- разделения сценариев профиля, достижений, верификации, CV и активности;
- выноса бизнес-логики обновления профиля из serializers/helpers в service
  layer;
- уточнения legacy-полей профиля и старых форматов payload.

## Основные возможности

- регистрация пользователя;
- подтверждение email;
- повторная отправка письма подтверждения;
- получение и обновление профиля пользователя;
- получение текущего пользователя;
- публичный список пользователей;
- список специалистов: mentors, experts, investors;
- роли пользователя: member, mentor, expert, investor;
- дополнительные данные профиля: образование, опыт, языки, ссылки;
- навыки пользователя и подтверждение навыков другими пользователями;
- достижения пользователя и файлы достижений;
- проекты пользователя, проекты лидера и лайкнутые проекты;
- подписанные проекты пользователя;
- программы пользователя и теги программ;
- события, на которые зарегистрирован пользователь;
- onboarding stage;
- принудительная верификация пользователя администратором;
- скачивание CV;
- отправка CV на email;
- отслеживание `last_login` и `last_activity`;
- новости пользователя через общий модуль `news`.

## Архитектура

- `users/models.py` - модель пользователя, роли, достижения, ссылки,
  образование, опыт, языки и подтверждения навыков.
- `users/views.py` - HTTP endpoints и orchestration logic для профиля,
  регистрации, CV, достижений, проектов, программ и событий.
- `users/serializers.py` - request/response contracts, validation и часть
  бизнес-логики обновления профиля.
- `users/helpers.py` - вспомогательная логика подтверждения email, обновления
  достижений/ссылок и force verify.
- `users/filters.py` - фильтры списков пользователей и специализаций.
- `users/managers.py` - queryset helpers для пользователей, достижений и
  лайков проектов.
- `users/permissions.py` - permissions для достижений и expert-сценариев.
- `users/authentication.py` - JWT authentication с обновлением
  `last_activity`.
- `users/signals.py` - side effects при создании/обновлении пользователя и
  сбросе пароля.
- `users/tasks.py` - Celery-задача отправки CV на email.
- `users/services/` - подготовка данных для CV и пользовательской активности.
- `users/admin.py` - настройка Django admin.
- `users/tests/` - regression-тесты API, serializers/helpers, permissions,
  signals и сервисов модуля.

## Основные сущности

- `CustomUser` - пользователь.
- `Member` - профиль участника.
- `Mentor` - профиль ментора.
- `Expert` - профиль эксперта, включая связь с партнерскими программами.
- `Investor` - профиль инвестора.
- `UserAchievement` - достижение пользователя.
- `UserAchievementFile` - файл достижения.
- `UserLink` - ссылка пользователя.
- `UserEducation` - образование пользователя.
- `UserWorkExperience` - опыт работы пользователя.
- `UserLanguages` - язык пользователя.
- `UserSkillConfirmation` - подтверждение навыка пользователя другим
  пользователем.
- `LikesOnProject` - лайк проекта пользователем.

## API

- `POST /auth/users/` - регистрация пользователя.
- `GET /auth/users/` - список пользователей для admin.
- `GET /auth/public-users/` - публичный список пользователей.
- `GET /auth/specialists/` - список специалистов.
- `GET /auth/users/<id>/` - детали пользователя.
- `PUT /auth/users/<id>/` - полное обновление профиля.
- `PATCH /auth/users/<id>/` - частичное обновление профиля.
- `DELETE /auth/users/<id>/` - удаление пользователя.
- `GET /auth/users/current/` - профиль текущего пользователя.
- `GET /auth/users/projects/` - проекты текущего пользователя.
- `GET /auth/users/projects/leader/` - проекты, где текущий пользователь лидер.
- `GET /auth/users/liked/` - лайкнутые проекты текущего пользователя.
- `GET /auth/users/<id>/subscribed_projects/` - подписки пользователя на
  проекты.
- `GET /auth/users/current/programs/` - программы текущего пользователя.
- `GET /auth/users/current/programs/tags/` - теги программ текущего
  пользователя.
- `GET /auth/users/current/events/` - события текущего пользователя.
- `GET /auth/users/roles/` - дополнительные роли пользователей.
- `GET /auth/users/types/` - типы пользователей.
- `GET /auth/users/specializations/nested/` - категории специализаций с
  вложенными специализациями.
- `GET /auth/users/specializations/inline/` - плоский список специализаций.
- `GET /auth/users/achievements/` - список достижений.
- `POST /auth/users/achievements/` - создание достижения текущего пользователя.
- `GET /auth/users/achievements/<id>/` - детали достижения.
- `PUT /auth/users/achievements/<id>/` - полное обновление достижения.
- `PATCH /auth/users/achievements/<id>/` - обновление достижения.
- `DELETE /auth/users/achievements/<id>/` - удаление достижения.
- `PUT /auth/users/<id>/set_onboarding_stage/` - обновление стадии онбординга.
- `POST /auth/users/<id>/force_verify/` - принудительная верификация
  пользователя администратором.
- `POST /auth/users/<user_id>/approve_skill/<skill_id>/` - подтверждение навыка.
- `DELETE /auth/users/<user_id>/approve_skill/<skill_id>/` - удаление
  подтверждения навыка.
- `GET /auth/users/download_cv/` - скачивание CV текущего пользователя.
- `GET /auth/users/send_mail_cv/` - отправка CV текущего пользователя на email.
- `POST /auth/logout/` - logout через blacklist refresh token.
- `POST /auth/resend_email/` - повторная отправка письма подтверждения.
- `GET /auth/account-confirm-email/` - подтверждение email по query token.
- `GET /auth/account-confirm-email/<key>/` - legacy route подтверждения email.
- `POST /auth/reset_password/` - сброс пароля через
  `django_rest_passwordreset`.
- `GET /auth/users/<id>/news/` - новости пользователя.
- `POST /auth/users/<id>/news/` - создание новости пользователя.
- `GET /auth/users/<id>/news/<news_id>/` - детальная новость пользователя.
- `PATCH /auth/users/<id>/news/<news_id>/` - редактирование новости
  пользователя.
- `DELETE /auth/users/<id>/news/<news_id>/` - удаление новости пользователя.
- `POST /auth/users/<id>/news/<news_id>/set_viewed/` - просмотр новости.
- `POST /auth/users/<id>/news/<news_id>/set_liked/` - лайк новости.

## Основные сценарии

### 1. Регистрация и подтверждение email

Пользователь регистрируется через `POST /auth/users/`. После создания учетной
записи пользователь остается неактивным до подтверждения email.

Система отправляет письмо с token. При переходе по ссылке подтверждения
пользователь активируется и получает access/refresh token для входа в сервис.

### 2. Профиль пользователя

Пользователь получает и обновляет свой профиль через `/auth/users/<id>/` или
`/auth/users/current/`.

Профиль включает:

- базовые поля пользователя;
- роль и данные роли;
- навыки;
- образование;
- опыт работы;
- языки;
- ссылки;
- достижения;
- проекты и программы пользователя.

Телефон отображается только владельцу профиля, потому что используется в CV.

### 3. Роли пользователя

У пользователя есть основной `user_type`:

- member;
- mentor;
- expert;
- investor.

При создании пользователя сигнал создает соответствующий role-profile:
`Member`, `Mentor`, `Expert` или `Investor`.

### 4. Навыки и подтверждения

Навыки пользователя хранятся через `core.SkillToObject`.

Другой авторизованный пользователь может подтвердить навык через
`/auth/users/<user_id>/approve_skill/<skill_id>/`. Пользователь не может
подтверждать собственные навыки.

### 5. Достижения

Достижения пользователя доступны через `/auth/users/achievements/`.

Создавать достижения можно только для текущего пользователя. Файлы достижения
привязываются через `UserFile` и должны принадлежать текущему пользователю.

### 6. Проекты, программы и события

Модуль отдает связанные с пользователем данные:

- проекты текущего пользователя;
- проекты, где пользователь является лидером;
- лайкнутые проекты;
- подписанные проекты;
- программы пользователя;
- события, на которые пользователь зарегистрирован.

Основная бизнес-логика этих сущностей находится в связанных модулях
`projects`, `partner_programs` и `events`.

### 7. CV

Пользователь может скачать CV в PDF или отправить его на свой email.

PDF собирается из данных профиля пользователя. Для защиты от повторных
запросов используется короткий cache cooldown.

### 8. Активность пользователя

JWT authentication обновляет `last_activity` пользователя не чаще одного раза
за throttle window. Если cache временно недоступен, сервис пытается обновить
активность напрямую в базе и не блокирует основной запрос пользователя.

## Ограничения и правила

- Email пользователя уникален.
- Новый пользователь создается с `is_active = False` до подтверждения email.
- Профиль может редактировать только владелец.
- `email`, `password` и `is_active` не обновляются через обычный update
  профиля.
- Пользователь с типом `member` не может менять `user_type` через текущий flow.
- Телефон скрыт от других пользователей.
- Файлы достижений должны принадлежать текущему пользователю.
- Скачивание и отправка CV ограничены cooldown.
- `last_activity` обновляется с throttle, чтобы не писать в базу на каждый
  запрос.
- В модуле остаются legacy-поля `key_skills` и `speciality`; актуальные поля -
  `skills` и `v2_speciality`.

## Тесты

Текущие тесты лежат в `users/tests/` и разделены по сценариям.

### API и пользовательские сценарии

- `test_auth_api.py` - регистрация, duplicate email, invalid payload,
  `last_login`, `/auth/users/current/` и удаленные legacy routes.
- `test_profile_api.py` - обновление профиля владельцем, nested profile data,
  skills, links, защита чужого профиля, скрытие телефона и неизменяемость
  `user_type` для member.
- `test_achievements_api.py` - создание достижений, запрет создания за другого
  пользователя, привязка файлов и запрет чужих файлов.
- `test_onboarding_verification_api.py` - onboarding stage, resend verify email,
  force verify и role-profile signal.
- `test_skill_confirmations_api.py` - подтверждение навыков другим
  пользователем, запрет self-confirmation и удаление подтверждения.
- `test_user_lists_api.py` - публичные списки пользователей, фильтры,
  проекты пользователя, проекты лидера и лайкнутые проекты.
- `test_cv_api.py` - скачивание CV, отправка CV на email и cooldown.

### Бизнес-логика и инфраструктурные сценарии

- `test_auth_activity.py` - `last_activity` с throttle, устойчивость к ошибкам
  cache и database update.
- `test_models_validators.py` - role-profile creation, ordering score,
  validation языков, опыта, файлов достижений, лайков, возраста, имени, года и
  телефона.
- `test_permissions.py` - permissions для достижений, expert-flow и
  отключаемой authentication.
- `test_signals.py` - `dataset_migration_applied` и создание role-profile.
- `test_activity_service.py` - подготовка данных пользовательской активности,
  отдельный подсчет участия в программах и проектов, поданных в программу.

Текущий уровень покрытия модуля по `coverage` - около 82%.
