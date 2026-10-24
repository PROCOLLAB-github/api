# BE01 — основа решения в программах

Дизайн D00 v3 утвержден пользователем 24 октября 2026 года. ТЗ: https://chatgpt.com/space/page_9632e9ed74588191b6b3e4b397d55175 . Контракт C00 1.0.0: `docs/contracts/program-solutions-v1/`.

## План и границы

Модели и аддитивная миграция: ProgramSolution с принадлежащими ему участниками, приглашениями и ответами; системные колонки формы; технический режим программы legacy_project по умолчанию. Старые данные не переносятся и не удаляются.

API: контекст программы, идемпотентное создание, чтение и список по C00. Создание сериализуется блокировкой программы и проверяет существующую заявку через принятый состав и капитанство, включая legacy. Капитан и единственная запись состава создаются атомарно. Project, самостоятельная Team и новая регистрация не создаются.

В BE01 нет PATCH/submit и команд состава/приглашений; permissions этих действий false. На этом этапе читать может своя команда и организатор/администратор программы. Политика эксперта и публикации подключается в BE07/BE08, до этого доступ не расширяется. Технический режим решения вручную включается только для тестовой новой программы после настройки формы; REL01 включает готовую функцию позже.

FE01 выполняется независимо по тем же схемам: модели, адаптеры, use cases, маршруты, явное ветвление по storage_mode и моки. Полный редактор и приглашения относятся к FE03–FE06.

Проверки: AC01/AC02/AC20/AC22; schema совместимость реальных HTTP ответов с C00; строгие запросы; отсутствие доступа из чужой программы; PostgreSQL миграции, уникальность и конкурентное создание; legacy regression. Публичные старые endpoints не меняются для legacy программ. В режиме solution старый POST создания проекта отклоняется.

## Verification и review от 24 октября 2026

Checked by source: diff от `origin/dev` f77b6048. Изменения только в контуре partner_programs и dev-зависимостях проверки C00. Создание блокирует строку программы; повтор возвращает 200, новый объект 201. Новый и старый ID не взаимозаменяемы. Запросы строго проверяются, ответы новых API имеют envelope C00. Права регистрации повторяют project_apply (исключение для менеджера, без автоматического исключения staff). Видимость ограничена своей командой и организатором/администратором. Состав, приглашения и сдача не имеют изменяющих endpoints.

Checked by tests: **147 tests PASS** на локальной изолированной PostgreSQL 18, Python 3.11, `procollab.settings_ci`:

```text
python manage.py test partner_programs.tests.test_solution_foundation partner_programs.tests.test_project_apply partner_programs.tests.test_case_fields partner_programs.tests.test_field_values partner_programs.tests.test_field_value_mutation partner_programs.tests.test_management_project_form_api projects.tests.test_competitive_team_policy projects.tests.test_team_security invites.tests.test_invite_integrity invites.tests.test_invite_decisions --settings=procollab.settings_ci --noinput --keepdb
```

15 новых проверок включают реальные конкурентные транзакции с разными соединениями, ограничения БД, приоритет прав/дедлайна, закрытые команды, snapshot чтения, strict input и валидацию реальных HTTP ответов JSON Schema из C00. Остальные проверки подтверждают прежние формы, проекты, приглашения и team policy. Добавлены dev-зависимости jsonschema и openapi-spec-validator; `poetry check --lock` PASS, lock 2.0 сохранен.

Checked by migration/checks: `manage.py check`, применение всех миграций на пустой локальной PostgreSQL, `makemigrations --check --dry-run` PASS. Миграция 0030 только добавляет структуры и варианты типов. `black --check` и `flake8` новых Python-файлов PASS. `validate_contract.py` PASS: 47 схем, 22 операции, 43 сценария. Это не означает реализацию всех операций C00: в BE01 доступны четыре операции контекста/создания/чтения/списка.

Checked in browser совместно с FE01: реальная JWT авторизация вымышленного пользователя, создание решения без Project, повторный вход в тот же ID, чтение вкладок и переход из программы. Старый режим создает Project и открывает `/office/projects/1/edit?...&programLinkId=1`. Тестовая БД после этих сценариев содержит одно решение новой программы и один проект старой.

Not checked: полный набор 693 старых тестов не завершился — Windows native PDF rendering сертификата завершился access violation; он не помечается PASS. PDF/сертификаты не затронуты. Полный suite остается проверкой Linux CI. Production, перенос данных BE10 и полный путь приглашений/сдачи QA01 не выполнялись.

| AC в scope BE01 | Evidence | Verdict |
| --- | --- | --- |
| AC01: решение без Project/Team | Новый API, отсутствие Project/связи, атомарный captain member; PostgreSQL tests и реальный браузер FE01 | PASS |
| AC02: повтор и гонка без дубля | Repeat 200 после дедлайна, неизменное имя; два соединения дают один ID и одну запись состава | PASS |
| AC20: изоляция программ | Чужой ID дает 404, чужой менеджер не читает; current_application берет точный program/link | PASS |
| AC22: старый контур | 132 связанные regression tests и старый браузерный путь; default legacy_project | PASS в scope BE01 |

Review: исправлены порядок ошибок прав/дедлайна по C00 и чтение сохраненного snapshot в деталях/списке. После исправлений 147 tests PASS. Оставшихся BLOCKER/MAJOR/MINOR в scope нет. Остальные AC относятся к BE02–BE10/FE02–FE08/QA01 и этим этапом не закрываются.

Порядок внедрения: backend с миграцией и выключенным режимом → FE01. Не включать режим для участников до BE02–BE09, FE02–FE08 и QA01/REL01. Отключение режима не скрывает чтение уже созданного решения. Миграции со старого Project нет; merge и deployment выполняет пользователь.
