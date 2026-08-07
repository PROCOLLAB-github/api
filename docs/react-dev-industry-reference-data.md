# Справочник отраслей React-dev

React-форма проекта загружает отрасли через `GET /industries/`. Endpoint возвращает
непагинированный массив объектов `id`, `name` и `datetime_created` непосредственно из
таблицы `industries_industry`.

Изолированная React-dev база создаётся отдельно от legacy dev и production. Schema
migration приложения `industries` создаёт таблицу, но исторически не добавляет в неё
справочные строки. Поэтому новая база может корректно отвечать `200 []`, а обязательное
поле отрасли в форме публикации останется без вариантов.

## Безопасное заполнение React-dev

Команда создаёт только отсутствующие названия из действующего legacy-справочника. Она
не удаляет, не переименовывает и не обновляет существующие строки, не фиксирует primary
key и безопасна для повторного запуска.

Перед любым изменением проверить план:

```console
python manage.py seed_react_dev_industries --confirm-react-dev --dry-run
```

После проверки выполнить в контейнере, подключённом именно к изолированной React-dev
базе:

```console
python manage.py seed_react_dev_industries --confirm-react-dev
```

Команда дополнительно требует `ALLOW_REACT_DEV_DEMO_SEED=True`. По умолчанию setting
равен `False`, поэтому запуск в production или legacy dev с обычной конфигурацией
завершается до записи данных. На production эту команду запускать нельзя.

После заполнения `GET /industries/` должен вернуть 27 элементов. Smoke-проверка проекта:

1. создать private draft через `POST /projects/workspace/`;
2. сохранить выбранный `industry` через `PATCH /projects/<id>/workspace/`;
3. повторно открыть workspace detail и проверить сохранённую отрасль;
4. заполнить остальные обязательные поля и отправить `draft=false`, `is_public=true`;
5. убедиться, что опубликованный Project сохранил тот же `industry`.
