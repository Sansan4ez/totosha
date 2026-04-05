RFC-011 Simple And Stable Production Deployment On NixOS
========================================================

Status
------

Draft (2026-04-05)

Context and motivation
----------------------

Репозиторий `totosha` уже реализован как single-host Docker Compose платформа:

- `core` ведёт агентный hot path и оркестрирует sandbox-контейнеры через Docker socket;
- `proxy` изолирует LLM secrets;
- `tools-api`, `scheduler`, `bot`, `admin`, `corp-db` общаются друг с другом по внутренней docker-сети;
- observability уже описана как Victoria stack + OTEL overlay;
- часть сервисов является optional и не нужна для первого production запуска.

Это важно, потому что production-решение должно быть не “идеологически чистым”, а простым и стабильным. Попытка переписать текущую архитектуру в native NixOS services без Docker:

- ломает существующую операционную модель проекта;
- усложняет sandbox orchestration в `core`;
- заставляет заново проектировать межсервисные контракты и state handling;
- не даёт пропорционального выигрыша в надёжности для первого production варианта.

Дополнительные вводные для этого RFC:

- `cli-proxy-api` остаётся в составе платформы и используется как upstream proxy для LLM provider flows;
- `base_url` для `proxy` указывает на `cli-proxy-api`;
- `Google Workspace MCP`, `mcp-test`, `docker-mcp` и `userbot` в первом production варианте не нужны;
- желательно включить Victoria Observability stack для контроля метрик, логов и трасс основного request path.

Цель RFC: зафиксировать production-схему, где **NixOS является hardened host и systemd/control plane**, а **`totosha` остаётся Docker Compose приложением**, запускаемым на этом хосте предсказуемо и без лишней инфраструктурной сложности.

Goals
-----

- Зафиксировать целевую production-топологию для одного NixOS VPS.
- Оставить `totosha` compose-native приложением и не переписывать сервисы в native NixOS units.
- Сохранить `cli-proxy-api` как обязательную часть LLM request chain.
- Включить в production только минимально необходимый набор сервисов:
  - `cli-proxy-api`
  - `proxy`
  - `corp-db`
  - `tools-api`
  - `scheduler`
  - `core`
  - `bot`
  - `admin`
- Включить Victoria Observability stack:
  - `victoriametrics`
  - `victorialogs`
  - `victoriatraces`
  - `otel-collector`
  - `alertmanager`
  - `vmalert`
  - `grafana`
- Держать внешний surface area минимальным:
  - публично открыт только SSH;
  - admin и observability UI доступны только через localhost binding и SSH tunnel.
- Разделить ответственность между репозиториями:
  - `totosha` отвечает за application compose topology;
  - `LAD-NixOS` отвечает за host OS, firewall, secrets materialization, systemd wrappers и backups.
- Зафиксировать операционный baseline: deploy, restart, rollback, backup, smoke, observability triage.

Non-goals
---------

- Переписывание `core`, `proxy`, `tools-api`, `scheduler`, `bot` и `admin` в native NixOS service modules.
- Kubernetes, Nomad, Swarm или другая оркестрация сверх Docker Compose.
- Публичная публикация admin panel, Grafana, Victoria endpoints или внутренних API в v1.
- Включение `Google Workspace MCP`, `mcp-test`, `docker-mcp`, `userbot` в baseline production topology.
- Полное observability-покрытие всех контейнеров через универсальный docker log shipping в v1.
- Автоматический GitHub CI/CD pipeline как обязательная часть первого запуска.

Current state analysis
----------------------

### 1. Compose already is the real runtime contract

Текущий runtime-контракт системы описан в `docker-compose.yml` и overlay для observability:

- сервисные зависимости определены через `depends_on`;
- secrets читаются как file-based Docker secrets;
- `core` работает с `/var/run/docker.sock`;
- `admin` уже завязан на localhost binding;
- observability overlay уже прокидывает OTEL env в основной request path.

Следовательно, production-решение должно усиливать этот контракт, а не заменять его другой моделью.

### 2. `cli-proxy-api` должен остаться, но текущий локальный layout хрупок

Сейчас `cli-proxy-api` собирается из `../CLIProxyAPI`, а его runtime state смонтирован из соседнего checkout. Для локальной разработки это приемлемо, но для production это слишком неявный и хрупкий dependency boundary.

Production-дизайн должен сохранить сервис, но убрать зависимость от случайного sibling path.

### 3. Project already has a reasonable observability baseline

Проект уже содержит:

- `docker-compose.observability.yml`;
- Victoria stack;
- OTEL collector;
- app-level instrumentation в `core`, `bot`, `proxy`, `tools-api`, `scheduler`;
- runbook и smoke/triage docs.

Это хороший фундамент. Правильное решение не в создании нового observability-стека, а в включении существующего baseline в production topology.

### 4. The public ingress surface can stay tiny

Для первого production варианта:

- Telegram bot работает по polling;
- Google OAuth не нужен;
- admin panel не должна быть публичной;
- Grafana не обязана быть публичной.

Значит, production можно держать без HTTPS ingress и без Caddy в hot path приложения. Это упрощает схему и уменьшает blast radius.

Recommended decision
--------------------

Целевое решение для production:

1. Один NixOS VPS используется как hardened Docker host.
2. `totosha` разворачивается через `docker compose`, а не через native NixOS services.
3. NixOS управляет только host-side аспектами:
   - Docker Engine;
   - firewall;
   - root-owned runtime directories;
   - materialization secrets из `sops-nix`;
   - systemd wrappers вокруг compose;
   - backup timers;
   - SSH-only operational access.
4. Production stack делится на три слоя:
   - application stack;
   - observability stack;
   - operator-only flows.
5. `cli-proxy-api` сохраняется как upstream proxy для LLM providers, а `proxy` работает поверх него.
6. Внешний доступ к admin/Grafana/Victoria endpoints не публикуется; оператор использует SSH tunnel.

Why this is the right simplicity/stability tradeoff
---------------------------------------------------

- Это минимально расходится с текущим кодом и docs.
- Это не ломает `core` sandbox orchestration.
- Это не создаёт second system вокруг деплоя.
- Это позволяет быстро получить production с rollback и observability.
- Это оставляет путь к будущему ужесточению security и автоматизации без смены базовой runtime-модели.

Alternatives considered
-----------------------

### Option A. Rebuild everything as native NixOS services

Плюсы:

- единая declarative OS model;
- меньше Docker runtime abstraction.

Минусы:

- `core` зависит от Docker orchestration semantics;
- требуется переписать service boundaries и runtime assumptions;
- сильно дороже в реализации и выше риск регрессий;
- не является “простым и стабильным” первым production решением.

Verdict:

- отклонено.

### Option B. Keep Docker Compose and run only the app stack

Плюсы:

- минимальный объём работ;
- быстрое внедрение.

Минусы:

- нет production-grade visibility по метрикам/логам/трассам;
- сложнее triage реальных инцидентов;
- нет наблюдаемого baseline для latency и ошибок.

Verdict:

- отклонено как недостаточно operationally safe.

### Option C. Keep Docker Compose, keep `cli-proxy-api`, enable Victoria stack, publish nothing except SSH

Плюсы:

- минимально сложный production baseline;
- хорошо совпадает с текущим устройством проекта;
- даёт observability, rollback path и понятную операционку;
- не требует публичного web ingress.

Минусы:

- остаётся Docker как основной runtime;
- часть инфраструктурных контейнеров не получает полного OTEL coverage в v1.

Verdict:

- принято.

High-level behavior
-------------------

### Request path

1. Пользователь пишет Telegram-боту.
2. `bot` отправляет запрос в `core`.
3. `core` вызывает `tools-api`, `scheduler`, `proxy` и при необходимости sandbox execution.
4. `proxy` читает secrets локально и перенаправляет запрос в `cli-proxy-api`.
5. `cli-proxy-api` работает как upstream LLM provider proxy.
6. Ответ возвращается в `core`, затем в `bot`, затем пользователю.

### Observability path

1. `core`, `bot`, `proxy`, `tools-api`, `scheduler` экспортируют traces/logs/metrics в `otel-collector`.
2. `otel-collector` пересылает:
   - metrics в `victoriametrics`;
   - logs в `victorialogs`;
   - traces в `victoriatraces`.
3. `grafana` используется для операторского просмотра, `vmalert` и `alertmanager` для базовых алертов.

### Operator path

1. Оператор подключается по SSH.
2. При необходимости открывает tunnel на localhost-only сервисы:
   - admin
   - grafana
   - core/proxy/tools-api/scheduler health/metrics endpoints
3. Запускает deploy/restart/smoke/backup через root-owned scripts или systemd units.

Target production topology
--------------------------

### Always-on application stack

- `cli-proxy-api`
- `proxy`
- `corp-db`
- `tools-api`
- `scheduler`
- `core`
- `bot`
- `admin`

### Always-on observability stack

- `victoriametrics`
- `victorialogs`
- `victoriatraces`
- `otel-collector`
- `alertmanager`
- `vmalert`
- `grafana`

### Disabled in production baseline

- `google-workspace-mcp`
- `mcp-test`
- `docker-mcp`
- `userbot`

### Operator-only, started manually

- `corp-db-worker`

Network and ingress design
--------------------------

### Public ingress

В v1 публично открыт только:

- `22/tcp` for SSH

Ни один из следующих портов не публикуется наружу:

- `3000` admin
- `3200` proxy
- `4000` core
- `4001` bot HTTP sidecar
- `8100` tools-api
- `8400` scheduler
- `8317` cli-proxy-api
- `3003` grafana
- `8428` VictoriaMetrics
- `9428` VictoriaLogs
- `10428` VictoriaTraces
- `4317/4318/13133` OTEL collector

### Localhost-only operator access

Для operator access сервисы должны быть доступны только через localhost binding или firewall-closed localhost-reachable endpoints:

- `admin` -> `127.0.0.1:3000`
- `grafana` -> `127.0.0.1:3003`
- app service debug endpoints -> `127.0.0.1:*`

Рекомендуемый operational path:

- `ssh -L 3000:127.0.0.1:3000 ...`
- `ssh -L 3003:127.0.0.1:3003 ...`

### Internal Docker networks

- `agent-net`: основной inter-service network
- `cliproxy-net`: отдельная сеть только для `proxy` и `cli-proxy-api`
- `observability-net`: сеть observability stack

Принцип:

- `proxy` является единственным мостом между app stack и `cli-proxy-api`;
- observability stack не должен быть доступен извне;
- Postgres остаётся внутренним сервисом и не публикует порт на host.

CLIProxyAPI integration
-----------------------

`cli-proxy-api` остаётся обязательным сервисом production-топологии, но production layout меняется следующим образом:

- нельзя зависеть от локального relative path `../CLIProxyAPI`;
- сервис должен использовать фиксированный production path, например:
  - `/opt/cli-proxy-api/` как отдельный checkout, pinned to explicit commit;
  - или vendored checkout в заранее известной директории под root control.

Обязательные правила:

- `base_url.txt` для `proxy` указывает на `http://cli-proxy-api:8317/v1`;
- `proxy` остаётся единственным сервисом, который знает `base_url` и `api_key`;
- остальные сервисы говорят только с `proxy`;
- внешний `127.0.0.1:8317` bind допускается только как operator convenience, не как публичный ingress.

Target directory layout on the host
-----------------------------------

Рекомендуемая host layout:

```text
/opt/totosha/
  app/                    # checkout репозитория totosha
  secrets/                # rendered runtime secrets (*.txt), root-owned
  workspace/              # persistent app workspace
  workspace/_shared/      # persistent shared data
  backups/                # pg_dump + tar archives

/opt/cli-proxy-api/
  app/                    # pinned checkout CLIProxyAPI
  config.yaml
  auths/
  static/
  logs/
```

Принципы:

- application source и runtime state не смешиваются;
- secrets не лежат внутри git checkout;
- `cli-proxy-api` имеет собственный понятный lifecycle, а не “случайный соседний каталог”.

Secrets and configuration model
-------------------------------

Source of truth for production secrets:

- `sops-nix` в infra repository (`LAD-NixOS`)

Runtime contract for `totosha`:

- file-based secrets в `/opt/totosha/secrets/*.txt`, совместимые с текущим `docker-compose.yml`

Это означает:

- NixOS materializes secrets из SOPS;
- compose consumes rendered files без изменения app runtime model.

Минимальный набор секретов для v1:

- `telegram_token.txt`
- `base_url.txt`
- `api_key.txt`
- `model_name.txt`
- `admin_password.txt`
- `postgres_password.txt`
- `corp_db_rw_dsn.txt`
- `corp_db_ro_dsn.txt`

Дополнительно:

- `zai_api_key.txt` только если реально нужен web search

State and persistence
---------------------

### Must be persisted

- `/opt/totosha/secrets/`
- `/opt/totosha/workspace/`
- `/opt/totosha/workspace/_shared/`
- `corp-db` data
- `/opt/cli-proxy-api/auths/`
- `/opt/cli-proxy-api/logs/`

### Can be treated as reconstructable or short-retention

- Victoria metrics/logs/traces data
- Grafana local state, если dashboards provisioned from files
- `corp-db-worker` runtime artifacts

### Backups

В v1 достаточно:

- регулярного `pg_dump` для `corp-db`;
- tar-архивов `workspace/_shared` и `secrets`;
- tar-архива `cli-proxy-api/auths`;

Сырые snapshots Docker named volumes не являются обязательным baseline. Для first production проще и надёжнее делать logical backup там, где это возможно.

Observability design
--------------------

### Baseline decision

Victoria stack включается в production baseline сразу.

Используются:

- `victoriametrics/docker-compose.yml`
- `docker-compose.observability.yml`

### Covered services in v1

Полноценный OTEL coverage ожидается для:

- `core`
- `tools-api`
- `proxy`
- `scheduler`
- `bot`

Это уже соответствует текущему observability overlay и существующим runbooks.

### Partial coverage in v1

Для следующих сервисов в v1 допускается неполное observability coverage:

- `cli-proxy-api`
- `admin`
- `corp-db`

Для них baseline остаётся таким:

- `docker logs`
- container healthchecks
- host-level monitoring

Причина: цель v1 — простой и стабильный production, а не тотальное переинструментирование всей платформы.

### Required production observability behavior

- Все instrumented app services экспортируют `metrics`, `logs`, `traces`.
- `grafana` доступна оператору через SSH tunnel.
- OTEL collector не публикуется публично.
- `docker compose` для app stack всегда запускается вместе с observability overlay.
- Rebuild/recreate сервисов без overlay считается operationally invalid.

### Retention

Для первого production варианта observability retention может быть короткой:

- metrics: 7-14 days
- logs: 3-7 days
- traces: 1-3 days

Это достаточно для triage и не усложняет storage budget.

Security model
--------------

### Host security

NixOS отвечает за:

- SSH key-only access;
- fail2ban;
- firewall default deny;
- отсутствие публичных внутренних портов;
- root-owned deploy scripts и secrets directories.

### Application security

`totosha` сохраняет текущую security model:

- `proxy` изолирует secrets;
- `core` использует sandbox orchestration через Docker;
- `admin` не публикуется наружу;
- default production access mode должен быть `admin_only`, не `public`.

### Explicit production rules

- `ACCESS_MODE=admin` или эквивалентный `admin_only` baseline.
- `admin_password` не может оставаться дефолтным.
- `userbot`, `docker-mcp`, `mcp-test`, `google-workspace-mcp` не стартуют в baseline profile.
- `docker.sock` остаётся доступен только тем контейнерам, которым он действительно нужен (`core`; в v1 можно оставить и `docker-mcp` выключенным).

NixOS responsibilities
----------------------

Infra repository (`LAD-NixOS`) должен реализовать:

- включение Docker Engine;
- создание root-owned каталогов в `/opt/totosha` и `/opt/cli-proxy-api`;
- materialization SOPS secrets в `/opt/totosha/secrets`;
- systemd unit для observability stack;
- systemd unit для application stack;
- backup script + timer;
- smoke script + manual run target;
- firewall rules;
- operator documentation.

Recommended NixOS units:

- `totosha-observability.service`
- `totosha-app.service`
- `totosha-backup.service`
- `totosha-backup.timer`

Compose responsibilities
------------------------

Application repository (`totosha`) остаётся источником истины для:

- container topology;
- intra-stack environment variables;
- OTEL overlay;
- app-specific healthchecks;
- service profiles;
- observability compose overlay.

Это означает, что infra repo не должен пытаться переопределять бизнес-логику сервисов. Его задача — аккуратно завернуть существующий compose runtime в production-safe host contract.

Deployment workflow
-------------------

### Initial bootstrap

1. Поднять NixOS host.
2. Включить Docker, firewall, fail2ban и runtime directories.
3. Разместить:
   - `totosha` checkout в `/opt/totosha/app`
   - `cli-proxy-api` checkout в `/opt/cli-proxy-api/app`
4. Материализовать secrets.
5. Проверить `base_url.txt = http://cli-proxy-api:8317/v1`.

### Start order

1. Start observability stack.
2. Start application stack with observability overlay.
3. Run smoke checks:
   - `proxy /ready`
   - `core /health`
   - `bot /health`
   - `tools-api /health`
   - `scheduler /health`
   - Victoria / Grafana health

### Routine deploy

1. Обновить application checkout до целевого git SHA.
2. При необходимости обновить `cli-proxy-api` checkout до pinned SHA.
3. Запустить:
   - observability stack stays up
   - app stack `up -d --build` вместе с overlay
4. Выполнить smoke.
5. При ошибке откатить checkout до предыдущего SHA и повторить `up -d --build`.

Rollback model
--------------

В v1 rollback intentionally остаётся простым:

- rollback application source to previous git SHA;
- rerun compose with the same overlay;
- secrets and persistent state не трогаются.

Это проще и надёжнее, чем ранняя попытка делать image registry promotion или сложную multi-stage release orchestration.

Implementation outline
----------------------

### Phase 1. Freeze the topology

- Подготовить production-specific compose baseline:
  - always-on: `cli-proxy-api`, `proxy`, `corp-db`, `tools-api`, `scheduler`, `core`, `bot`, `admin`
  - disabled: `google-workspace-mcp`, `mcp-test`, `docker-mcp`, `userbot`
- Зафиксировать `ACCESS_MODE` production default как admin-only.
- Зафиксировать `base_url` contract для `cli-proxy-api`.

### Phase 2. Prepare NixOS host wrapper

- Добавить NixOS modules для Docker host.
- Добавить root-owned runtime directories.
- Добавить systemd units вокруг compose.
- Добавить SOPS-backed secret rendering.

### Phase 3. Enable observability in prod

- Поднять Victoria stack.
- Обеспечить запуск app stack только с observability overlay.
- Закрыть observability endpoints от публичного доступа.
- Проверить request correlation через `request_id`, `trace_id`, `span_id`.

### Phase 4. Add backups and smoke

- Реализовать `pg_dump` backup.
- Архивировать `workspace/_shared`, `secrets`, `cli-proxy-api/auths`.
- Добавить smoke script для post-deploy validation.

### Phase 5. Harden production docs

- Обновить install/deploy docs под production topology.
- Явно пометить текущие local/dev-oriented инструкции как не production source of truth.

Testing approach
----------------

### Static validation

- `docker compose config` для app stack
- `docker compose -f victoriametrics/docker-compose.yml config`
- `docker compose -f docker-compose.yml -f docker-compose.observability.yml config`

### Host validation

- NixOS evaluation/build of target host config
- Проверка systemd units на clean start/stop/restart
- Проверка firewall rules

### Runtime validation

- `proxy /ready`
- `core /health`
- `bot /health`
- `tools-api /health`
- `scheduler /health`
- `grafana /api/health`
- Victoria query `up`
- VictoriaTraces service list
- VictoriaLogs query by `service.name`

### Functional validation

- end-to-end message through Telegram bot
- one agent request using `proxy -> cli-proxy-api`
- one corp-db backed request
- one scheduled task creation/execution

### Backup validation

- `pg_dump` restore into temporary database
- tar restore test for `_shared`
- auth state restore test for `cli-proxy-api`

Operational acceptance criteria
-------------------------------

- Один NixOS VPS поднимает весь production baseline без Kubernetes и без native rewrite сервисов.
- Production stack стартует через systemd-managed Docker Compose.
- `cli-proxy-api` входит в обязательный request chain, а `proxy` использует его адрес в `base_url`.
- `Google Workspace MCP`, `mcp-test`, `docker-mcp` и `userbot` не входят в baseline production deployment.
- Victoria Observability stack поднят и получает telemetry хотя бы от `core`, `tools-api`, `proxy`, `scheduler`, `bot`.
- Ни `admin`, ни observability endpoints не доступны публично из интернета.
- Оператор может открыть admin и Grafana через SSH tunnel.
- Деплой приложения и rollback выполняются без изменения OS configuration и без ручной правки контейнеров на сервере.
- Секреты управляются через infra repo и материализуются как file-based runtime secrets, совместимые с текущим compose.
- Регулярные backups `corp-db`, `workspace/_shared`, `secrets` и `cli-proxy-api/auths` выполняются автоматически.

Future work
-----------

- Добавить OTEL/filelog coverage для `cli-proxy-api`, `admin` и, при необходимости, `corp-db`.
- Вынести `cli-proxy-api` на pinned image digest, если появится надёжный release artifact.
- Добавить CI-driven deploy pipeline поверх этого baseline.
- Позже, при появлении реальной необходимости, рассмотреть HTTPS ingress для selected operator endpoints через Caddy/Tailscale/VPN.

Summary
-------

Принятое решение для production: **NixOS как hardened Docker host, `totosha` как Docker Compose приложение, `cli-proxy-api` в обязательной LLM chain, optional сервисы выключены, Victoria stack включён, публичный ingress отсутствует кроме SSH**.

Это самый короткий путь к простому и стабильному production запуску без архитектурного раздвоения и без лишнего migration risk.
