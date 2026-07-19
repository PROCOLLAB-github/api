# API Safety Fix Plan: Scoped Throttling

Дата: 2026-07-19.

Implemented in this PR:

- Added `PostOnlyScopedRateThrottle`, a small DRF throttle helper that applies scoped throttling only to `POST` requests.
- Added scoped throttling to public/user-facing high-risk endpoints:
  - `POST /auth/users/`
  - `POST /auth/resend_email/`
  - `POST /auth/reset_password/`
  - `POST /api/token/`
  - `POST /programs/<id>/register_new/`
- Added env-configurable rates in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` without enabling global `DEFAULT_THROTTLE_CLASSES`.
- Scoped rate keys are `auth_register`, `auth_resend_email`, `auth_reset_password`, `token_obtain`, and `program_register_new`.
- Added `.env.example` entries for the new rates.
- Added targeted tests that override each selected scope to `1/min` and assert the second request is throttled.

Not changed in this PR:

- No serializers, payload schemas, success response bodies, or existing business validation branches were changed.
- No production/dev GitHub Actions, deploy files, release process, nginx, or proxy configuration were changed.
- No global throttling was enabled for the rest of the API.

Proxy/IP note:

DRF throttles anonymous requests by client ident. The current backend has `SECURE_PROXY_SSL_HEADER`, but broader trusted proxy/IP handling must be coordinated with infrastructure before relying on IP throttles as an abuse boundary. Reverse proxy config should ensure client IP headers are overwritten by trusted infrastructure, not accepted from arbitrary clients.
