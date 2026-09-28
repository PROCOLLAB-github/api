# DEV: поиск и фильтр программ для Experts

Exact base: `11f1e66a85e266d57fc6b0f8c080ee8cd0683f19` (`origin/dev` после fetch).
Ветка: `feature/dev-expert-admin-search`; exact head указан в Draft PR.

## Изменение

В `users/admin.py`, `ExpertAdmin`, добавлены три стандартные настройки:

```python
search_fields = ("user__first_name", "user__last_name", "user__email")
list_filter = ("user__partner_program_profiles__partner_program",)
list_select_related = ("user",)
```

`list_display = ("id", "user")` сохранён. Кастомного frontend, шаблона или
`SimpleListFilter` нет. Black также перенёс строки существующего выражения
`CustomUserAdmin.formfield_for_manytomany`; его поведение не изменено.

**Search:** стандартный Django Admin `icontains` по трём полям. Отдельные слова
соединяются через AND, поля для каждого слова — через OR. Поэтому полное имя
ищется по нескольким полям без собственной нормализации/логики. Это не точное
сравнение ФИО: запрос «Иван Иванов» также может найти «Пётр Иванов», поскольку оба
слова входят в фамилию. Такое стандартное поведение явно покрыто тестом.

**Filter:** `RelatedFieldListFilter` по legacy пути
`Expert.user → CustomUser.partner_program_profiles → PartnerProgramUserProfile.partner_program`.
Choices формируются из существующих PartnerProgram через их `__str__`, включая
программы без экспертов. Справа стандартные `FILTER`, `By partner program`, `All`.
Без выбранного значения остаются все Experts, в том числе без программы. Search и
program filter работают одновременно; `All` снимает программу, сохраняя search.

**Duplicates:** явный `.distinct()` не добавлен. В установленном из lockfile Django
4.2.11 `ChangeList.get_queryset()` распознаёт reverse FK как потенциальный источник
дублей и использует коррелированный SQL `EXISTS`. Эксперт в двух программах
отображается один раз без фильтра и один раз в каждой программе. Тесты сравнивают
список ID и количество строк, а не множества, чтобы не скрыть дубли.

Несуществующий числовой program ID даёт пустой список; нечисловой ID проходит
стандартную обработку Admin — redirect на `?e=1` без HTTP 500.

**Performance:** `list_select_related = ("user",)` загружает строки и пользователей
одним SQL-запросом. Проверено на queryset changelist с фильтром и без фильтра:
получение всех строк и чтение `str(expert.user)` укладывается в один запрос.
У самого changelist остаются стандартные запросы counts, choices, session/permissions;
утверждение об одном запросе относится к строкам таблицы вместе с пользователями.

Модели, schema, migrations, staff/superuser permissions и бизнес-правила не менялись.
Angular, React, Application/Team/Submission/current_application не затронуты.

## Проверки

Локальная среда: Python 3.11.15, Django 4.2.11, PostgreSQL 18.1 (UTF-8, ICU ru-RU),
Black 22.12.0. Отдельный временный кластер PostgreSQL на loopback, отдельные базы
для тестов и browser QA, `procollab.settings_ci`. DEV/PROD данные не использовались.

- `python manage.py test users.tests.test_expert_admin --noinput --verbosity 2`:
  **18 tests OK**, exit 0.
- `python manage.py test --noinput --verbosity 1 --keepdb` (режим существующего CI):
  **919 tests OK**, 458.293 s, exit 0; test failures/errors 0.
- `python manage.py check`: **0 issues**, exit 0.
- `python manage.py makemigrations --check --dry-run`: **No changes detected**, exit 0.
- Black / Flake8 для `users/admin.py` и `users/tests/test_expert_admin.py`: exit 0.
- `git diff --check`: exit 0.

Первый полный запуск без `--keepdb`: **919 tests OK**, 502.401 s, но **exit 1**
на teardown — оставшиеся 21 соединение помешали `DROP DATABASE`. Ошибок тестовых
сценариев не было. Повторный запуск использует существующий режим CI `--keepdb`
с отдельной очисткой изолированной локальной БД; test harness не изменён.

18 тестов покрывают search по имени/фамилии/email/словам полного имени, регистр,
пустую выдачу, All, программы, отсутствие регистрации, двойную регистрацию,
search+filter, отсутствующий/невалидный ID, запросы user column, запрет доступа
для non-staff и staff без Expert permissions.

## Browser QA

Настоящий `/admin/users/expert/` с обычным входом superuser на изолированной
локальной PostgreSQL-базе. API/HTML не подменялись. Chrome 154.0.8037.57, 1440 px:
**17 assertions, 11 состояний выдачи, 0 JS errors / HTTP 500**, exit 0.
Проверены поиск по имени, фамилии, email, полному имени, отсутствие результата,
filter, search+filter, All, двойная регистрация и невалидный/несуществующий ID.

- [Все эксперты: search и sidebar filter](all-experts.png).
- [Иванов + FinFor25-26](search-and-program.png).
- [Численные результаты](browser-results.json).
- [Browser script](browser-acceptance.cjs).

Для воспроизведения нужен отдельный PostgreSQL, зависимости из lockfile и
`procollab.settings_ci`. После `manage.py migrate` на пустой QA-базе вызовите
`ExpertAdminTests.setUpTestData()` из `users.tests.test_expert_admin`, сохранив
PK программы и экспертов в `.cache/expert-admin-qa/fixtures.json` с ключами
`program`, `otherProgram`, `ivan`, `anna`, `otherIvanov`, `noProgram`.
Стандартный Django staticfiles runserver можно вызвать через
`call_command(Command(), "127.0.0.1:8340", use_reloader=False, insecure_serving=True)`;
`Command` импортируется из `django.contrib.staticfiles.management.commands.runserver`.
Это обходит только локальное ограничение Daphne runserver на `--insecure`;
настройки приложения, cookies, auth и permissions не менялись.
Запустите `node docs/expert-admin/browser-acceptance.cjs` из корня репозитория;
`PLAYWRIGHT_MODULE` и `CHROME_PATH` могут указывать на внешние Playwright/Chrome.
Login script использует только известную тестовую учётную запись из fixtures.

Merge и deploy не выполнялись.
