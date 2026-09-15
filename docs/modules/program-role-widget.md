# Read-only виджет программы для Angular

DEV-база backend: `ed5244bd4a098bd0f1cee0f5e380dd67bdd61a96`.
Парный Angular основан на `99c8813a66f89560a946eab7d1de73ab2925d0f5`.
Ветка: `feature/dev-program-role-analytics-widget`; итоговые SHA и ссылки указаны в Draft PR.

## Контракт

`GET /programs/{id}/analytics-widget/`, обязательная аутентификация.
Параметры `role`, `user_id` и `project_id` не используются для авторизации или выбора проекта.
GET не изменяет бизнес-данные. Ответ содержит только ветвь разрешённой роли:

```json
{
  "program_id": 12,
  "role": "participant",
  "is_competitive": true,
  "participant": {
    "participant_project": { "id": 5, "name": "StudyFlow", "program_link_id": 34 },
    "case_provided": true,
    "case_name": "Цифровой сервис",
    "stage": "review",
    "submission_open": true
  }
}
```

Пример иллюстрирует форму, значения не являются данными DEV. Остальные ветви:

- `organizer`: `participants`, `projects`, `submitted_solutions`, `participants_without_project`.
- `expert`: `mode` (`distributed` / `open`), `assigned`, `remaining`, `evaluation_ends` (ISO datetime либо null).
- `participant_project` и `case_name` могут быть null. `stage`: `none`, `not_submitted`, `submitted`, `review`, `evaluated`, `not_applicable`.
- Неприменимые счётчики — null: open assigned/remaining; неконкурсные submitted_solutions и персональные distributed-счётчики. Реальный срок оценивания передаётся также для open.

401 — нет входа; 403 — нет роли в этой программе; 404 — программа отсутствует; 409 — противоречивые связи команды, не выбор первого проекта. Angular не отображает raw response body и не подменяет ошибку нулями.

## Источники и переиспользование

| Показатель | Источник и правило | Права / изменение |
| --- | --- | --- |
| Роль | `program.is_manager(user)` → `program.experts` → `PartnerProgramUserProfile` | Только текущая программа; global staff/user_type, наличие назначений и клиентские claims не дают роль |
| Проект команды | PartnerProgramProject текущей программы; Project.leader либо Exists Collaborator | Новый локальный selector; максимум две строки для обнаружения несоответствия правилу одной команды. Один проект без выбора |
| Кейс | `get_program_case_field`: точный name="case"; PartnerProgramFieldValue текущей связи | Нет fallback по label, первому option, глобальному Project или другой программе |
| Участники и без проектов | `_get_participant_metrics` основной аналитики | Distinct user; без проекта = нет лидерства и Collaborator на проекте программы; черновик учитывается |
| Проекты и решения | `_get_solution_metrics` основной аналитики | Единица учёта — PartnerProgramProject; отправленные — submitted-связи, не пользователи |
| Этап проекта | `_solution_rows` основной аналитики | Неподанный → not_submitted; submitted без начала → submitted; назначение/начатая оценка → review; общая итоговая классификация → evaluated |
| Остаток эксперта | `annotated_assignment_queryset`, фильтр текущих program/expert, SQL aggregate | Незавершённые назначения, включая not_ready, а не число незаполненных критериев |
| Срок | `PartnerProgram.datetime_evaluation_ends` | Не срок подачи или окончания программы |

Distributed completion остаётся общим: submitted-связь, ненулевой набор критериев и заполнение всех критериев назначения; для проекта должны завершиться все назначения. Записанная допустимая оценка 0 считается заполненной. Неотправленный проект не завершён даже при существующих оценках.

В open сохранено существующее правило основной аналитики: ProjectScore по критерию программы даёт проекту evaluated. Это не новая формула виджета. Назначения и персональный остаток в open не выдумываются; frontend сохраняет переход в оценивание и однократно показывает реальный срок.

Дедлайн не участвует в определении оценённости. Баллы, личности экспертов и закрытые результаты участнику не сериализуются. Неконкурсная программа не получает искусственную обязательную сдачу.

## Изоляция контрактов

Используются только Angular-модели Project, Collaborator, PartnerProgramProject, PartnerProgramUserProfile, Expert, ProjectExpertAssignment, Criteria, ProjectScore и существующие поля программы.

`current_application` остаётся legacy-контрактом лидера с прежней семантикой. Для члена команды null в этом поле не влияет на новый `participant_project`. Просмотр виджета не даёт права редактировать поля или отправлять проект вместо лидера.

React-модели Application, Team, Submission, SubmissionExpertAssignment, Evaluation, их serializers/services/endpoints не используются и не изменяются. Менеджерские API не открываются другим ролям.

В существующий program detail добавлен только контекстный boolean `is_user_expert`; он не раскрывает description/links незарегистрированному эксперту. Правила регистрации, выбора/сохранения case, сдачи, назначений, завершения и публикации сохранены. Нет миграций, зависимостей или изменений CI/Docker/workflows.

Сервис использует общие SQL-агрегации. Не сериализует большую аналитику и не загружает проекты/регистрации в браузер. Тест проверяет постоянное число SQL-запросов при росте числа проектов и отсутствие INSERT/UPDATE/DELETE.

## Проверки 14.09.2026

Python 3.11, существующее Poetry-окружение. Локальные SQLite и PostgreSQL 18; production/DEV базы не использовались.

```sh
DEBUG=True python manage.py test partner_programs.tests.test_role_widget_api partner_programs.tests.test_program_detail partner_programs.tests.test_program_link_fields_api partner_programs.tests.test_manager_analytics_api partner_programs.tests.test_assignment_analytics_api project_rates.tests --noinput
```

Targeted: 120 тестов PASS. Новые 15 тестов проверяют роли и приоритет, эксперта без регистрации/назначений, чужую программу, manager-only API, лидера/члена команды, несколько программ с разными case/status, неизменность current_application и прав сдачи, integrity 409, точное поле case, distributed/open, 0/partial/full/not_ready, черновики и командную метрику, изоляцию назначений, реальный дедлайн, bounded SQL/read-only.

Уникальность регистраций уже обеспечена схемой: тест проверяет отклонение дубликата и единственный учёт пользователя. Ограничения БД ради теста не менялись; общая аналитика сохраняет Count(distinct user).

| Команда | Фактический результат |
| --- | --- |
| `DEBUG=True python manage.py test --noinput` (SQLite) | 849 тестов, OK (skipped=4), 570,439 с. После тестов exit 1: WinError 32 при удалении test_db.sqlite3 |
| `python manage.py test --noinput` с временным settings на основе `procollab.settings_ci` (PostgreSQL) | 849 тестов, 1 failure: `feed.tests.test_feed_api.FeedAPITests.test_feed_returns_project_news_as_news_content`, ожидалось news, получено project. Teardown также встретил 21 незакрытое соединение; после завершения процесса временная БД удалена |
| Тот же feed-тест отдельно на исходном `ed5244bd...`, PostgreSQL | PASS. Причина сбоя полного прогона не установлена; полный suite не объявляется успешным, feed-код не менялся |
| `python -m flake8` всех tracked Python и отдельно новых файлов | PASS |
| `python -m black --check` новых файлов и urls | PASS |
| `DEBUG=True python manage.py check` | 0 issues |
| `DEBUG=True python manage.py makemigrations --check --dry-run` | No changes detected |
| `python -m mypy partner_programs/services/role_analytics.py partner_programs/serializers/role_analytics.py partner_programs/widget_views.py` | Не выполнен typecheck: существующий mypy.ini объединяет две строки plugins в один import (`mypy_django_plugin.main\nmypy_drf_plugin.main`), exit 2. Конфигурация не менялась |
| `git diff --check` | PASS |

Скриншоты трёх ролей/нулевых состояний и сравнение исходной геометрии находятся в парном Angular PR, `docs/program-role-widget/README.md`. Браузерный smoke использует реальные Angular-компоненты и локальные fixtures; живой DEV вход/сдача/оценивание в браузере не проверялись.

## Зависимость будущего DEV-развёртывания

Сначала backend-контракт и detail-флаг, затем Angular-виджет. Изменение read-only, миграций нет. Merge, deploy и PROD-операции не выполнены.
