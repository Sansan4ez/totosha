Product Observability Data Contract
===================================

Status
------

- Decision: **Accepted**
- Effective date: 2026-08-30
- Owner: LocalTopSH operator
- Applies to: internal VictoriaMetrics, VictoriaLogs, VictoriaTraces, Grafana, and OTEL telemetry

Decision
--------

LocalTopSH intentionally permits user request text, intermediate processing evidence, and assistant response text in its private, short-retention observability system. This data is required to reconstruct a product turn, diagnose routing and retrieval failures, compare successful and unsuccessful answers, and improve product quality.

This is an explicit exception to a generic payload-free observability policy. The exception applies only to the operator-controlled Victoria stack. It does not authorize sending telemetry content to an external observability provider.

Product Turn Contract
---------------------

An observable product turn consists of:

1. the user request;
2. the processing path, including selector, argument builder, route, tool, retrieval, fallback, finalizer, status, and latency evidence where instrumented;
3. the final assistant response;
4. logs and aggregate metrics correlated with the same execution.

Implementations may store request and response content as span attributes, span events, or structured log records. Bounded copies in retry and failure records are allowed when they explain an actual processing decision. Payload placement may evolve, but it must preserve correlation across the turn.

Correlation
-----------

The following identifiers are the supported join keys:

- `request_id` joins application logs and the HTTP request;
- `trace_id` joins logs to the distributed trace;
- `span_id` identifies the emitting processing stage;
- route and tool identifiers (`selected_route_id`, `selected_business_family_id`, `selected_leaf_route_id`, `route_stage`, `tool_name`) explain the selected execution path;
- a pseudonymous turn or conversation identifier may be used for multi-turn analysis, but must never be a metric label.

Product content must not be copied into metric labels. Metrics are aggregate views of the same traffic and use bounded dimensions only.

Allowed Content
---------------

The internal short-retention telemetry store may contain:

- user request text;
- final assistant response text;
- normalized, rewritten, token-fallback, or retry queries that were actually used;
- selector and route decisions;
- tool names, bounded tool arguments, result summaries, and errors needed for diagnosis;
- model, token-usage, status, timing, and retrieval evidence;
- business names, object names, addresses, and other personal or commercially sensitive text supplied by a user.

The operator accepts that ordinary product text may contain personal data. The Victoria stack must therefore be treated as a restricted internal data system rather than as public diagnostics.

Prohibited Content
------------------

Telemetry must not intentionally record:

- API keys, access tokens, passwords, cookies, session credentials, private keys, or authorization headers;
- secret files, environment dumps, or credential-bearing configuration;
- the complete system prompt;
- hidden model reasoning or chain-of-thought;
- unrelated sandbox or workspace file contents that were not part of an explicit user-visible operation.

High-volume raw model/debug dumps remain disabled by default outside local development. If a credential is accidentally included by a user, treat it as a security incident: rotate the credential and let short retention expire the captured copy.

Signal Responsibilities
-----------------------

### Traces

Traces represent the processing path. They may carry request, response, and processing artifacts as attributes or events. They must retain `request_id` and route/tool correlation fields so an operator can explain why an answer was produced.

### Logs

Logs provide searchable product-turn and failure evidence. Full or bounded request/response records and meaningful retry queries are permitted. Avoid gratuitous duplication: operational messages should prefer correlation identifiers when another record in the same turn already carries the needed content.

The generic `HTTP request completed` record remains payload-free. It is the stable correlation record, not the product-content record.

### Metrics

Metrics are aggregate operational and product-quality signals. Raw requests, responses, retry queries, user IDs, request IDs, trace IDs, random identifiers, SKUs, addresses, and other unbounded values are forbidden in metric labels.

Retention
---------

Default persistent Compose retention is:

- metrics: 14 days;
- logs: 7 days;
- traces: 7 days.

Deployments may shorten these periods. Extending them requires an explicit operator decision, a storage review, and corresponding documentation. Backups must not silently turn short-retention telemetry into permanent archives.

Access Boundary
---------------

- Victoria and Grafana host ports bind to `127.0.0.1` only.
- Remote access uses an SSH tunnel.
- Grafana uses its own operator credential.
- Victoria endpoints and OTEL ingestion endpoints are not public APIs.
- Access is limited to operators responsible for product quality, incident response, and security.

External Providers
------------------

This contract covers internal observability only. Transmission of prompts, documents, queries, embeddings, or responses to an external model or embeddings provider requires a separate decision and documentation. In particular, the OpenRouter embeddings boundary is tracked independently by `totosha-yfnk`.

User Notice
-----------

Operators must tell users that requests, processing evidence, and responses may be retained in the private observability stack for up to 7 days for diagnostics, security, and product improvement. Users must be told not to submit passwords, tokens, private keys, or other credentials.
