# PROD: выборочный перенос аналитики и стандартной обложки

База: `4c49f5918e571708f872c532b1f5154fc2a03428`.
Ветка: `release/prod-program-analytics-project-cover`.

Перенесены только DEV merge commits:

- #742: `8ed5670d2123dd1f1b53668567ad60bde8641bcc`;
- #743: `dd3d48b121a1fd0668857c9b8766bb588be2360b`.

## Различия с DEV и сохранение PROD

Конфликт detail программы разрешён вручную: существующий
`current_project_application` сохранён с прежней семантикой лидера.
DEV-поле `current_application` не добавлено и публичный контракт не переименован.
Из #742 добавлен `is_user_expert`, необходимый для отображения секции эксперту
без member-роли. Это добавление вызвало описанное ниже падение строгого
регрессионного теста набора полей ответа.

PROD уже использует `project_analytics` и `project_assignment_analytics`.
Новый сервис виджета вызывает существующие `_participant_metrics`,
`participants_without_team_rows`, `_annotated_solution_rows` и
`annotated_assignment_queryset`. Количество проектов и отправленных решений
считается SQL aggregate по тем же связям программы; большая аналитика не
сериализуется. Дополнительные DEV commits не переносились.

Endpoint reset-cover использует существующие permissions ProjectDetail.
Глобальное удаление файлов, модели, миграции, правила оценки и сдачи,
React-контракты, зависимости, CI/Docker/workflows не менялись.

## Локальные проверки 18.09.2026

Python 3.11, PostgreSQL 18 на localhost, изолированные временные БД.
Рабочие DEV/PROD БД не использовались. Настройки основаны на
`procollab.settings_ci`, включён NEXTGEN_SURFACE_ENABLED для регрессии контрактов.

| Проверка | Результат |
| --- | --- |
| Targeted: widget, reset-cover, Project permissions, program detail/fields, legacy analytics, оценивание | 200 тестов, OK, 57,708 с |
| `python manage.py test --verbosity 1 --keepdb` | 1554 теста, failures=3, skipped=3, 811,056 с, exit 1 |
| `python manage.py check` | 0 issues |
| `python manage.py check --tag models` | 0 issues |
| `python manage.py makemigrations --check --dry-run` | No changes detected |
| Black изменённых Python-файлов | PASS |
| flake8 всех tracked Python-файлов | PASS |
| `git diff --check` | PASS |

Все три падения полного прогона — subtests
`ProgramCurrentProjectApplicationTests.test_existing_production_detail_contract_is_preserved`:
анонимный пользователь, посторонний пользователь и участник-организатор.
Тест сравнивает точный набор полей detail с serializer и не ожидает добавленный
`is_user_expert: false`. Сам `current_project_application` исключён из этого
сравнения; его selector и семантика не менялись. Не следует трактовать это
падение как доказательство изменения прав или выбора проекта.

Тест не ослаблялся, полный прогон не объявляется зелёным. По STOP-условию задачи
релиз остановлен до PR, snapshot, merge и deployment. Angular full suite также
завершился с exit 1 из-за необработанного teardown-таймера ngx-autosize.

## Порядок будущего релиза

После устранения блокеров и нового полного зелёного прогона нужны отдельные
PROD PR и свежий PROD snapshot. Backend развёртывается первым, Angular после
подтверждённой работоспособности новых API. Этот документ не подтверждает
развёртывание и не заменяет фактические runtime receipt и smoke.
