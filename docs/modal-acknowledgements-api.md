# Подтверждения одноразовых пользовательских окон

Продуктовые окна хранят состояние на backend, поэтому подтверждение действует для аккаунта во
всех браузерах и на всех устройствах. Cookie consent в этот контракт не входит и остаётся локальным
состоянием браузера.

## Поля состояния

- `CustomUser.verification_notice_acknowledged_at` — пользователь ознакомился с ожиданием
  верификации.
- `CustomUser.profile_fill_prompt_acknowledged_at` — пользователь явно закрыл напоминание о
  заполнении профиля.
- `PartnerProgramUserProfile.welcome_acknowledged_at` — участник ознакомился с приветствием
  конкретной программы.

Поля nullable. Обычный `PATCH /auth/users/<id>/` возвращает их только владельцу и не разрешает
изменять. Загрузка detail не записывает acknowledgement.

## Idempotent actions

- `POST /auth/users/current/acknowledge-verification-notice/` возвращает актуальный собственный
  профиль.
- `POST /auth/users/current/acknowledge-profile-fill-prompt/` возвращает актуальный собственный
  профиль.
- `POST /programs/<program_id>/acknowledge-welcome/` возвращает
  `{"welcome_acknowledged_at": "<datetime>"}`.

Повторный POST сохраняет исходный timestamp и отвечает `200`. Program action доступен только
участнику соответствующей программы; посторонний пользователь получает `404`.

`GET /programs/<program_id>/` для участника содержит read-only поле
`welcome_acknowledged_at`. Для собственного профиля current/detail serializers содержат оба
пользовательских timestamp; в ответе чужого профиля эти системные поля отсутствуют.
