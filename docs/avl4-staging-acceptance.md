# Staging Flowsint в AVL4 — 2026-10-16

Статус: развёрнуто на `avl-ya-test`; авторизованная API- и браузерная приёмка пройдена.
Авторизация: явный запрос пользователя на подготовку и развёртывание на `avl-ya-test`.

- Адрес: `https://flowsint.sc.avl.team`, DNS подтверждён.
- Первый кандидат: `flowsint-20261016-ea3bd2d69` (выполнен откат).
- Активный успешный релиз: `flowsint-20261016-c2fd84b89`.
- Предыдущий успешный релиз: `source-feed-link-20261016-d1f849d3`.
- Backend SHA: `c2fd84b8979c425588efb76036ccb4c395b9ba30`.
- UI SHA: `f59c3668478c4a8d2e7f5fcd949164784ba9ebcc`.
- Flowsint SHA: `ce31d94f0b803ced8e1caaee192ed6ca080a836d`.

## Подготовка

- [x] Проверены здоровые существующие сервисы, DNS и ресурсы сервера.
- [x] Исходники опубликованы, три checkout синхронизированы штатным workflow
  через `git pull --ff-only`; SHA подтверждены, серверные изменения не сбрасывались.
- [x] Новый Compose-компонент и четыре файла секретов, отдельные PostgreSQL/Neo4j,
  общая сессия, runtime JSON, SDK, ingress и health checks подготовлены.
- [x] Проверено совпадение root ingress snippet с предыдущим релизом;
  снимок snippet и metadata контейнеров сохранены приватно в кандидате.
- [x] Существующие incoming credentials проверены по хешам активного релиза;
  созданы только новые Flowsint settings, без копирования старых секретов на контроллер.
- [x] Offline release tests: 87 проверок, 13 пропущены из-за отсутствия локального
  исполняемого Caddy; остальные успешны. JS auth-page tests: 4 passed.
  Compose: 12 компонентов / 56 сервисов; Ansible syntax успешно.
- [x] Monitoring: 81 целевой тест, ESLint и сборка с TypeScript успешны.
- [x] Образы собраны на сервере, manifest и immutable image IDs сохранены.
- [x] Применён root HTTPS snippet с validate/reload и сохранением остальных routes.
- [x] Применён частичный application release, схема и health checks проверены.
- [x] Сквозная HTTPS/SSO/API/браузерная приёмка завершена.
- [x] Подтверждено сохранение контейнеров вне выбранного набора.

Сбой первого GitLab fetch исправлен повтором штатной синхронизации. Проверка SHA
остановила преждевременную попытку сборки до создания образов/переключения сервисов.

## Применение и проверка

Выбранный набор: `flowsint-postgres`, `flowsint-neo4j`, `flowsint-api`,
`flowsint-worker`, `flowsint-ui`, `auth`, `cards`, `main-panel`, `monitoring-ui`, `caddy`.
Meet, LiveKit и существующие workers не входят в обновление.

[Staging runbook](../../../../AVLTEAM/projects/avl4-monorepo-py/avl-deploy/avl-ya-test/FLOWSINT.md)
описывает сборку из трёх SHA, дополнение root ingress, частичное применение и откат.
Журналы Docker build и приложения остаются в приватном каталоге сервера.
Пользователь самостоятельно вошёл в выделенном окне браузера. Проверка выполнена
через его сессию тестового администратора; пароли не извлекались. Созданы только
синтетические проекты `Flowsint staging acceptance 03ea886c99 A/B`, две карточки,
расследование и граф. Проект A после проверки отзыва снова включён.

### Подтверждённые результаты

- `releases/current` указывает на успешный релиз; фактические `.Image` выбранных
  контейнеров совпадают с immutable runtime snapshot. ID всех невыбранных
  контейнеров сохранились, включая Meet/LiveKit и существующие workers.
- PostgreSQL, Neo4j, API, worker, UI, Auth, Cards, Main Panel и Monitoring healthy;
  application Caddy running. Обе конфигурации Caddy прошли validate/reload.
- Одноразовый init успешен: Alembic head `e4f5a6b7c8d9`, ограничение Neo4j
  `avl4_material_identity`. Повторный init с сохранёнными volumes успешен.
- Публичный HTTPS с проверкой сертификата: `/health` и runtime JSON возвращают
  HTTP 200 с ожидаемым JSON; `application=flowsint-ui`, `authBypass=false`.
  В Monitoring задан same-origin API `/flowsint`.
- Анонимный API возвращает 401 с `x-avl-auth-guard: session-rejected`;
  внутренний импорт закрыт 404 через оба публичных домена. Самостоятельный
  `/api/auth/token` отключён (404). Анонимный браузер направляется в общий Keycloak.
- Через настоящие HTTPS API созданы расследование/граф и две карточки с одинаковым
  заголовком. Передача Cards → Flowsint → SQL/Neo4j успешна; материалы различаются
  по ID источника. Проверены snapshot, provenance и обратная ссылка Monitoring.
- Повтор operation ID возвращает тот же результат; новый operation ID для той же
  карточки возвращает `existing`. Шесть параллельных передач дают один материал.
- Чтение расследования с проектом B запрещено. Отключение синтетического проекта A
  привело к HTTP 403 за 0,1 секунды; после включения доступ восстановлен.
- В браузере Monitoring: карточка → «Добавить в расследование» → выбор
  расследования/графа → «Добавить карточку» → «Открыть в Flowsint».
  Граф показывает два материала, общий main_panel и правильный проект.
  `Open in Monitoring` открывает оригинальную карточку с тем же `pid`.
- Переключение проекта A → B через личный кабинет main_panel сбрасывает маршрут
  на `/dashboard#pid=<B>`; список расследований пуст, материалы A не отображаются.

CLI приёмки: `deploy/flowsint_acceptance.py` из канонической staging-конфигурации.
Первый запуск выявил отсутствующий `Origin` в самом CLI; защита приложения вернула
403. CLI исправлен, повторная полная приёмка успешна. Изменение не требует
пересборки сервисов. Сессионный файл хранился вне Git с правами 0600 и удалён
после проверки; отчёт содержит только безопасные идентификаторы результатов.

### Immutable image IDs

| Сервис | Image ID |
| --- | --- |
| flowsint-postgres | `sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94` |
| flowsint-neo4j | `sha256:8b66506593508dbfc8083b7fc73045168de33a95c65e26f1ded8f85ad3852408` |
| flowsint-api, flowsint-worker | `sha256:7d35c07b8b2a27013949b0cb236adf4de2668c1693d93fe7a4ade3ec9667cd4c` |
| flowsint-ui | `sha256:bf4fae5f8925a6d287c77a78fb3905960fc530f7fca4c324f5ccc52b83c69366` |
| auth | `sha256:a21b8ffcc58d0259deeef9a2747f2d27a52c4df908e155fb62ca376dddd57609` |
| cards | `sha256:37c14a60d4a17e9cceca0ddc9e09b46323174c140bf4eb8a0903e11ccd2c24a7` |
| main-panel | `sha256:df6dc863541ea89060094499260643f2bd9f36f07369ed9110a3eae4445a07b3` |
| monitoring-ui | `sha256:d536248508fd64f0c03a7efbf56eead2c6471daa4dd4d1795f9d96fddcd62f81` |
| caddy | `sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b` |

### Границы приёмки

На staging использовался тестовый администратор. Сотрудничество двух обычных
участников, сбои API и CAS проверялись ранее на локальном стеке; на staging эти
сценарии повторно не выполнялись. Полное восстановление backup не проверено.
Расследования Flowsint пока не входят в project export/import AVL4.
Данные синтетической приёмки оставлены в двух явно обозначенных тестовых проектах.

## Исправление первого применения

Первый apply успешно инициализировал SQL и Neo4j, но Python health checks
превысили timeout 10 секунд. Restart count API/worker оставался 0.
Измерение в одноразовом контейнере: импорт Core **8,272 секунды**,
полное завершение процесса без обращения к БД **12,4 секунды**.
Helper автоматически восстановил предыдущие immutable images/конфигурацию,
удалив новые контейнеры и сохранив Flowsint volumes. Временный диагностический
контейнер удалён. Для повторного релиза timeout увеличен до 30 секунд,
initial grace — до 60 секунд; проверки хранилищ и Celery ping сохраняются.
