# BE08C1: снятие заявки с участия и сохранение работы

Пользователь согласовал административные исключения после сдачи с обязательным сохранением старых Project-программ и данных. Этот блок переносит действующее detach-поведение на ProgramSolution. Удаление регистрации остается отдельным BE08C2 и не подменяется архивированием.

## Модель и доступ

Сдача и участие независимы: status остается draft/submitted; archived_at/archived_by/archive_reason/archive_snapshot фиксируют снятие с участия. Обычные writers не устанавливают и не сбрасывают архивные поля. После архивирования model save/delete и обычные команды состава/материалов закрыты. Captain FK, принятый состав, ответы и UserFile остаются у той же сущности.

ProgramSolution.objects и обратная program.solutions возвращают активные работы. all_objects и base manager включают архив для сохранения связей и явных исторических чтений. Уникальность captain/program действует для активной заявки. Текущая заявка, exclusivity, предложения участников, оценивание, аналитика, результаты, назначения/распределение, напоминания и публикация используют активное участие. Historical score opt-in не восстанавливает назначения архивной работы.

Капитан и сохраненный состав читают собственный архив по прежнему solution URL; organizer/admin своей программы читает архив и историю. Экспертное назначение или сохраненная оценка не дает доступ к архивной работе. GET solutions по умолчанию participation=active; archived/all открывает собственные архивы и все архивы организатору. Optional participation в Solution/Summary сообщает состояние/дату/причину. Все permissions архивной работы false, team.is_frozen=true. Регистрация и возможность новой заявки проверяются независимо по прежним правилам срока/формы/creation flag.

## Подтвержденное снятие

POST `/programs/{program_id}/management/solutions/archive/preview/` принимает ids1–10000 без повторов; apply дополнительно требует точный preview_token. IDs — безопасные положительные целые; bool/string/fractional/unsafe, неизвестные body/query и пустой список запрещены. Действие доступно organizer/admin своей программы и solution mode. Legacy Project handlers и данные сохраняются.

Preview read-only показывает SolutionRef/version/status, количество оценок, отзываемых pending и снимаемых назначений. Архивная работа отмечена can_apply=False и null token. Signed proof действует10 минут, связан с actor/program/ids и fingerprint материалов/версий/состава/приглашений/файлов/оценок/назначений. Apply повторяет проверку прав и состояния под program → solutions → fields/members/invitations/UserFile locks. Срок, текущая форма и creation-only flag не запрещают административное снятие.

Операция атомарна для всей выборки. Все pending выбранных работ отзываются; обработанные приглашения остаются историей. Снимаются все назначения, включая оцененные, как при прежнем detach; оценки сохраняются. Привилегированный writer вызывает базовое ORM удаление только для подтвержденных назначений; обычная score protection остается. Каждая работа получает version+1 и собственное событие archive. Ошибка журнала откатывает архив, приглашения, назначения и версии всей транзакции. Повтор/stale/expired/чужой proof дает409 без повторной ревизии.

## Сохранение материалов

Archive snapshot содержит name/captain_id/members/form/answers/captured_at. Form помечена is_snapshot=true. Черновик остается черновиком с submitted_at=null и submission_snapshot=null; архивирование не имитирует сдачу. Для сданной работы исходный submission_snapshot и время сдачи не меняются. Читатели архива используют archive_snapshot, поэтому позднейшая настройка формы не меняет сохраненную работу.

Файлы архивного черновика защищены от удаления до CDN-вызова и через ORM/admin, как файлы сданной работы. Проверка использует unfiltered сохраненные snapshots и ответы; фильтр активных решений не ослабляет retention. Публикационный marker сохраняется, но архив отсутствует в публичном разделе программы и не публикуется повторно. Это не меняет согласованный неконкурсный publication scope; вопрос конкурсных несданных черновиков остается открытым.

SolutionAdministrativeChange поддерживает archive наряду с change_case/remove_member. Сохраняются actor/name/version/effects, unchanged before/after submission snapshots либо оба null для draft, отдельный archive_snapshot и причина. History detail доступен organizer/admin и для архива; старые case/member payloads не меняются. Public API текущего снятия устанавливает reason=detached; registration_removed зарезервирован для отдельной команды удаления регистрации.

## Контракт и реализация

C00 1.19.0:145 схем/55 операций/272 независимых сценария;250 прежних сценариев сохранены. Добавлены9 схем и2 операции. Четыре прежние схемы расширены optional participation/archive snapshot и archive ветвью history; остальные132 прежние схемы сохранены. Единственная измененная прежняя операция listSolutions получила participation filter;52 прежние операции неизменны. Shared OpenAPI/examples/README byte-identical с frontend.

0037 добавляет архивные поля/constraints и условную уникальность активного капитана, сохраняя прежние rows и4 события case/member. Миграция не архивирует, не переносит и не удаляет существующие работы или Project. Старые программы сохраняют storage mode и маршруты. Только новые локальные synthetic программы используются для rehearsal.

Frontend API layer содержит generated metadata/snapshot/union, bulk preview/apply port/repository/adapter/use cases и participation query. Нового organizer layout/routes/SCSS и навигации по архиву не добавлялось; соответствующий UI остается в первом выпуске и следует уже запрошенному D02/design approval. D03 и остальные исходные gates сохраняются.

## Проверки и выпуск

20 native PostgreSQL tests включают3 observed-lock races archive×archive/submit/score, draft/submitted/noncompetitive, bulk atomicity, scoped rights/proof, read-only retention, новую заявку той же команды, active selectors, historical assignments, public marker и file protection до CDN. Они входят в общий solution suite. Архивные snapshot и история проверены настоящим HTTP; [итоговый отчет](../qa/program-solutions-archive-20261025/README.md) содержит refs/логи/ограничения.

0037 применяется до запуска нового backend; backend/миграция предшествуют frontend. После первого archive event backend и фоновые workers должны сохранять правила C00 1.19: старый backend не понимает архив и не является допустимой версией отката. При остановке пилота creation-only flag выключает новое создание; архивные поля/снимки/историю не откатывать вниз, совместимый reader и writer guards сохранять. Флаг не выключает административные команды. Полный rollout/rollback rehearsal остается в REL01; merge/deploy/реальные переключения и BE10 этим этапом не выполняются.
