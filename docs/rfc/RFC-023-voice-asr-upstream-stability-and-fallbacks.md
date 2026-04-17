RFC-023 Voice ASR Upstream Stability and Fallbacks
=================================================

Status
------

Proposed

Date
----

2026-04-17

Related RFCs
------------

- RFC-011 фиксирует production deployment topology и operational expectations.
- RFC-013 вводит unified observability и trace propagation.
- RFC-015 разделяет runtime и benchmark pipelines, что важно для отделения production voice path от экспериментальных web-backed integrations.

Context and motivation
----------------------

За последние 30 минут в production voice path наблюдались периодические ошибки распознавания вида:

`ASR error: 403 {"error":{"message":"<html> ...`

Проверка живых логов и error artifacts показывает следующую цепочку:

1. `bot` получает голосовое сообщение и отправляет его в `http://proxy:3200/transcribe`.
2. `proxy` форвардит запрос в `cli-proxy-api /transcribe`.
3. `cli-proxy-api` отправляет запрос в upstream `chatgpt.com/backend-api/transcribe`.
4. Часть запросов получает не JSON transcript, а HTML Cloudflare challenge page.
5. Этот HTML возвращается обратно как `403`, и бот показывает ошибку пользователю.

За окно анализа было 15 вызовов `POST /transcribe`:

- 9 успешных;
- 6 завершились `403`;
- error rate составил около `40%`.

Ошибочные ответы приходили быстро, за `~65-230ms`, а успешные запросы обычно занимали `~0.7-1.4s`. Это указывает не на нормальную ASR inference failure, а на раннее upstream blocking.

Error logs `cli-proxy-api` прямо содержат:

- `Enable JavaScript and cookies to continue`
- `challenge-platform`
- `chatgpt.com`
- `/backend-api/transcribe`
- `__cf_chl_*`

Это означает, что проблема находится не в боте, не в proxy routing и не в voice decoding. Проблема в нестабильности web-session-based upstream transcription path.

Problem statement
-----------------

Текущий production ASR path опирается на ChatGPT web-backed `/backend-api/transcribe`, который:

- не является стабильным server-to-server ASR contract;
- может возвращать anti-bot challenge вместо machine-readable API response;
- зависит от состояния web auth session и cookies;
- не даёт надёжной привязки ошибок к конкретному credential в текущей observability;
- приводит к intermittent user-facing failures в обычном сценарии voice input.

В текущей схеме production voice pipeline нарушает базовый operational principle:

"Primary production dependencies должны быть machine-stable, server-oriented и наблюдаемые."

Goals
-----

- Сделать production voice recognition надёжным и предсказуемым.
- Убрать web challenge path из primary ASR flow.
- Сохранить возможность fallback, но не за счёт unstable happy-path.
- Улучшить observability до уровня конкретного upstream mode и конкретного auth credential.
- Сделать user-facing behavior мягким и понятным при временных ASR сбоях.

Non-goals
---------

- Переписывать весь Telegram voice flow.
- Менять UX text/agent orchestration за пределами voice pipeline.
- Убирать `cli-proxy-api` целиком из проекта.
- Строить сложную multi-provider orchestration в первой итерации.

Decision
--------

Production ASR должен быть переведён на stable API-first path.

Web-session-backed ChatGPT `/transcribe` не должен оставаться primary production ASR backend.

Предлагается следующая целевая политика:

1. Primary production ASR backend:
   - OpenAI-compatible `/v1/audio/transcriptions`
   - или dedicated Faster-Whisper / Whisper server
2. ChatGPT-compatible `/transcribe`:
   - только temporary compatibility mode;
   - либо explicit fallback mode;
   - либо operator-enabled degraded mode;
   - но не default production path.

Root cause
----------

Корневая причина ошибок: intermittent Cloudflare / anti-bot challenge на upstream `chatgpt.com/backend-api/transcribe`, вызванный использованием web-session-based transcription endpoint как production ASR backend.

Current architecture risk
-------------------------

В текущей схеме есть пять operational risks:

1. Web challenge risk
~~~~~~~~~~~~~~~~~~~~~

Upstream может вернуть HTML challenge page вместо ASR JSON без изменения локальной конфигурации.

2. Credential opacity
~~~~~~~~~~~~~~~~~~~~~

`cli-proxy-api` использует несколько `plus.json` auth files, но текущие `/transcribe` logs недостаточно явно показывают, какой credential вызвал конкретный `403`.

3. Incorrect error semantics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Для бота все такие случаи выглядят как generic `ASR error: 403`, хотя фактически это отдельный класс ошибки:

- `upstream_web_challenge`
- а не обычный `permission_error`
- и не обычный `quota_exceeded`

4. No credential quarantine
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Если один credential начал стабильно ловить challenge, routing всё равно продолжает использовать его в round-robin.

5. No graceful voice fallback
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Пользователь получает raw transcription failure, хотя система может:

- предложить отправить текст;
- сделать controlled retry;
- временно деградировать на другой backend.

Proposed architecture
---------------------

### 1. Introduce explicit ASR backend modes

Нужно ввести явный backend mode для ASR:

- `openai_compatible`
- `faster_whisper`
- `chatgpt_compat`

Production default должен быть:

- `openai_compatible` или `faster_whisper`

`chatgpt_compat` остаётся только как compatibility mode.

### 2. Move ChatGPT transcribe behind fallback boundary

Если `chatgpt_compat` вообще сохраняется, он должен работать как:

- explicit operator choice;
- или secondary fallback после stable backend failure;
- но не как primary path.

### 3. Add challenge-aware error classification

Когда upstream возвращает HTML со словами вроде:

- `challenge-platform`
- `Enable JavaScript and cookies to continue`
- `__cf_chl`

система должна классифицировать это как:

- `upstream_challenge`

а не как generic `403`.

### 4. Add per-credential observability and quarantine

Для `cli-proxy-api /transcribe` нужно логировать:

- auth file id или stable credential id;
- upstream mode;
- upstream status;
- error class;
- challenge detected boolean.

Если credential подряд получает несколько `upstream_challenge`, он должен:

- временно исключаться из round-robin;
- или переводиться в cooldown.

### 5. Improve bot-side user handling

При `upstream_challenge` или repeated ASR backend failures бот должен:

- не показывать сырое HTML-derived сообщение;
- отвечать коротко и понятно;
- предлагать повторить позже или прислать текст.

Пример acceptable user text:

`🎤 Временная ошибка распознавания речи на стороне сервиса. Попробуйте ещё раз или отправьте текстом.`

### 6. Add operator health signal for ASR mode

Нужен отдельный health/status signal:

- current backend mode;
- success rate за 5м / 30м;
- count of `upstream_challenge`;
- count of `403`;
- challenge rate per credential.

Это должно быть видно в logs и metrics без ручного чтения HTML payloads.

Implementation variants
-----------------------

Variant 1: Minimal mitigation on the current route
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Сохранить текущий production path без нового ASR route и без нового backend, но исправить самый болезненный пользовательский эффект.

Что делается:

- распознаётся challenge HTML как отдельный класс ошибки `upstream_challenge`;
- на `upstream_challenge` выполняется 1-2 повторных запроса с коротким backoff;
- пользователю больше не показывается сырой `403` и HTML-derived message;
- вместо этого бот отвечает нормализованным временным сообщением;
- `empty ASR response` перестаёт выглядеть как generic transport failure.

Плюсы:

- минимальный diff;
- можно внедрить быстро;
- снижает долю user-facing ошибок уже на текущем backend;
- не требует изменения topology.

Минусы:

- корневая причина не устраняется;
- нет per-credential quarantine;
- нет полной observability по challenge pattern.

Когда выбирать:

- как немедленный mitigation в production;
- когда нужна быстрая стабилизация UX без нового backend.

Variant 2: Harden current ChatGPT-compatible path
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Сохранить текущий `chatgpt_compat /transcribe`, но добавить полноценную protection/observability layer.

Что делается:

- всё из Variant 1;
- structured logging по `credential_id`, `backend_mode`, `error_class`;
- counters и traces для success/failure/challenge rate;
- cooldown/quarantine для credentials, которые подряд ловят challenge;
- улучшенный admin health/status.

Плюсы:

- заметно лучше operational visibility;
- снижает вероятность повторного использования деградировавшего credential;
- всё ещё не требует нового backend.

Минусы:

- web-backed upstream всё равно остаётся unstable dependency;
- это hardening, а не окончательное решение.

Когда выбирать:

- как следующий шаг после Variant 1;
- когда нужно заметно повысить устойчивость без смены ASR backend.

Variant 3: Move production to a stable API-first backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Перевести production default на stable ASR backend:

- dedicated OpenAI-compatible Whisper endpoint;
- или dedicated Faster-Whisper service.

`chatgpt_compat /transcribe` остаётся только как fallback/compatibility mode либо отключается по умолчанию.

Плюсы:

- самый надёжный вариант;
- machine-readable contract;
- меньше anti-bot риска;
- проще operational ownership в долгую.

Минусы:

- нужен отдельный backend или внешний стабильный endpoint;
- потребуется rollout и отдельная эксплуатация.

Когда выбирать:

- как долгосрочное целевое состояние production voice path.

Recommended phased approach
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Рекомендуемый порядок внедрения:

1. Сначала Variant 1.
2. Затем Variant 2, если текущий backend сохраняется.
3. Затем Variant 3 как целевая production архитектура.

Такой порядок даёт быстрый UX win без лишнего инфраструктурного шага и не закрывает дорогу к правильному долгосрочному решению.

Implementation outline
----------------------

Phase 1: Hardening and observability
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. В `cli-proxy-api /transcribe` добавить распознавание challenge HTML.
2. Ввести явные error classes:
   - `upstream_challenge`
   - `upstream_quota`
   - `upstream_auth`
   - `upstream_transport`
3. В логи добавить credential identifier и backend mode.
4. В metrics добавить counters:
   - `asr_transcribe_requests_total`
   - `asr_transcribe_failures_total`
   - `asr_upstream_challenges_total`
   - `asr_credential_cooldowns_total`
5. На bot side заменить raw surfaced `403` на нормализованное user-facing сообщение.

Phase 2: Credential protection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

6. Добавить cooldown/quarantine для credential после N challenge failures подряд.
7. Исключать quarantined credential из round-robin на ограниченное время.
8. В health/admin diagnostics показать список degraded credentials.

Phase 3: Stable production backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

9. Поднять или подключить stable OpenAI-compatible ASR backend.
10. Сделать его production default в `asr_config`.
11. Перевести `chatgpt_compat` в fallback-only или disabled-by-default mode.

Phase 4: Cleanup
~~~~~~~~~~~~~~~~

12. Обновить documentation и admin labels так, чтобы `chatgpt` больше не выглядел как recommended default.
13. Добавить manual runbook для ASR incident response.

Config and UX changes
---------------------

В админке ASR config нужно явно показывать:

- backend type;
- recommended production choice;
- warning for `chatgpt_compat`.

Если выбран `chatgpt_compat`, UI должен предупреждать:

"Этот режим использует web-compatible transcription path и может быть нестабилен в production."

Error handling behavior
-----------------------

Bot behavior
~~~~~~~~~~~~

При единичной ошибке:

- ответить короткой временной ошибкой;
- не показывать HTML или сырой upstream payload.

При repeated `upstream_challenge` за короткое окно:

- прекратить немедленные retries;
- предложить пользователю отправить текст;
- при наличии fallback backend попробовать fallback path.

Proxy behavior
~~~~~~~~~~~~~~

`proxy` должен оставаться thin transport layer и не парсить challenge HTML. Классификация должна происходить там, где видно upstream semantics, то есть в ASR backend adapter или `cli-proxy-api`.

Observability
-------------

Нужно добавить:

- structured log field `asr_backend_mode`
- structured log field `asr_error_class`
- structured log field `asr_credential_id`
- metric `asr_upstream_challenge_total`
- metric `asr_transcribe_status_total{status=...,backend=...,credential=...}`

Желательно также добавить span attributes:

- `asr.backend`
- `asr.credential_id`
- `asr.error_class`
- `http.upstream_status`

Testing approach
----------------

Unit tests
~~~~~~~~~~

- challenge HTML correctly maps to `upstream_challenge`
- plain `403` JSON quota maps to `upstream_quota`
- transport timeout maps to `upstream_transport`
- bot error formatter never exposes raw HTML

Integration tests
~~~~~~~~~~~~~~~~~

- simulated challenge response from `/transcribe`
- credential cooldown after repeated challenge
- fallback backend selected after challenge threshold

Manual tests
~~~~~~~~~~~~

1. Send short voice message when primary backend is healthy.
2. Inject synthetic challenge response and verify normalized user message.
3. Verify quarantined credential stops receiving traffic.
4. Verify admin/metrics show challenge counters.

Acceptance criteria
-------------------

- Production default ASR backend is no longer `chatgpt_compat`.
- HTML challenge responses are classified as `upstream_challenge`.
- Bot never shows raw HTML-derived ASR error text to the user.
- `/transcribe` logs can identify the credential and backend mode used for each failed request.
- Repeated challenge on one credential causes temporary credential quarantine.
- Metrics expose ASR success rate and challenge rate for the last 5m and 30m.
- Voice recognition remains functional when the primary stable backend is healthy.

Rollback
--------

Если stable backend rollout вызывает проблемы:

1. временно вернуть предыдущий ASR backend mode;
2. сохранить challenge classification и improved UX;
3. оставить credential observability и cooldown logic включёнными.

This rollback допустим как short-term мера, но не должен возвращать `chatgpt_compat` в статус long-term recommended production backend.
