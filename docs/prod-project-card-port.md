# Перенос lifecycle списка проектов на PROD

База master: `a5cdf03a8eef391671c92ccea439e52d4df7cb4f`.
Источник: DEV [#748](https://github.com/PROCOLLAB-github/api/pull/748),
head `2651a1f5e8ea168a9e1fbc193b0bc07fa8f33027`,
merge `19458b68e16d71741f4aeed1d2510d673cfbd3e2`.

Это выборочный перенос сериализации и prefetch. Ветка DEV целиком не переносится.
PROD-изменения профиля, throttling и ограничений detail сохраняются.

## Контракт с Angular

`GET /auth/users/projects/` и `GET /auth/users/projects/leader/` расширяют
`partner_program`: прежние `id/name` дополнены `program_link_id`, `program_id`,
`is_submitted`. `id` остаётся ID программы, `program_link_id` — PK связи,
`is_submitted` — `PartnerProgramProject.submitted`. Без связи возвращается `null`.

```json
{
  "id": 12,
  "name": "Программа",
  "program_link_id": 120,
  "program_id": 12,
  "is_submitted": true
}
```

`program_fields`, `program_field_values`, `can_submit` в list не добавляются.
Angular после CamelcaseInterceptor получает `partnerProgram.isSubmitted`.
Сданный проект отображается как «Сдан в программу / только просмотр» независимо
от роли. При неполном старом контракте карточка не обещает редактирование.

## Выбор связи и доступ

Для лидера и collaborator список выбирает legacy-связь с минимальным PK, как
существующий detail. Порядок создания, PK программы и порядок prefetch-кеша
не влияют на выбор. PROD detail для читателей только с ролью в программе
сохраняет ограничение eligible links: чужие закрытые данные не раскрываются.
Его реализация и права не меняются.

Оба list endpoint загружают `program_links` через ordered Prefetch с
`select_related("partner_program").order_by("pk")`. Пустой кеш считается
готовым результатом и не вызывает дополнительный SELECT.

Query-count regression измеряет 1 → 31 проект для обоих endpoint при прогретом
существующем кеше просмотров. Старые cache miss в `get_views_count` не изменены;
проверка защищает загрузку программ от нового N+1, включая проекты без связи.
Результат для обоих списков: 3 → 3 SQL-запроса (COUNT, страница, JOIN-prefetch).
Сериализация заполненного/пустого prefetch-кеша — 0 SELECT; fallback без кеша — 1.

## Проверки и последующее развёртывание

Перенесены contract tests #748: null/false/true, обратный порядок создания и кеша,
min PK, равенство list/detail, лидер/collaborator, отсутствие анонимного доступа
и query count. Дополнительно запускаются PROD access/submission tests, полный
PostgreSQL suite, Django check, Black, Flake8 и проверка отсутствия новых миграций.

Submission logic, current_application, case, React, зависимости и workflows
не меняются. Для будущего релиза backend-контракт нужен перед Angular-карточками.
После отдельно разрешённого deploy необходимо сравнить list/detail одного
тестового сданного проекта: `program_link_id` и `is_submitted` должны совпасть.
Эта задача готовит Draft PR; merge/deploy и изменение DEV не выполняются.
