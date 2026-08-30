Observability Policy
====================

Purpose
-------

Define the repository policy for sampling, retention, cardinality, and sensitive-data handling.

The repo-specific decision for product-turn payloads is recorded in
`docs/operations/product-observability-contract.md`. That contract is the explicit
exception for internal, short-retention request/processing/response telemetry.

Sampling
--------

- Local development and CI smoke may use `100%` trace sampling.
- Non-local environments should lower baseline trace sampling and document the effective value.
- Metrics are not sampled.
- High-volume debug logs must stay disabled by default outside local development.

Retention
---------

- Local Compose stacks are ephemeral by default.
- CI keeps smoke artifacts, not persistent Victoria volumes.
- Persistent environments must document trace, log, and metric retention explicitly.
- The supported persistent Compose defaults are metrics `14d`, logs `7d`, and traces `7d`.
- Extending payload-bearing log or trace retention requires an explicit operator decision and documentation.
- Backups must not silently preserve short-retention telemetry as a permanent archive.

Cardinality
-----------

- Do not place request ids, user ids, random UUIDs, prompt text, or raw URLs into metric labels.
- Prefer low-cardinality operational labels such as status, service name, route template, and error class.
- `request_id`, `trace_id`, and `span_id` may appear in logs and traces for correlation.
- Shared request metrics must keep labels limited to `service`, `method`, `route`, and `status`.
- Dedicated retrieval metrics may add bounded route/tool labels such as `selected_route_id`, `selected_route_kind`, `selected_source`, `knowledge_route_id`, `document_id`, and `tool_name` when those identifiers come from the published routing catalog or canonical tool set.

Sensitive Data
--------------

- Metrics, logs, and traces must not contain secrets, tokens, credentials, authorization headers, private keys, environment dumps, complete system prompts, or hidden model reasoning/chain-of-thought.
- Internal VictoriaLogs and VictoriaTraces may contain user requests, processing artifacts, retry queries, and assistant responses under `docs/operations/product-observability-contract.md`.
- Product payloads may contain personal or commercially sensitive text and must be treated as restricted operator data.
- Temporary high-volume raw model/debug logging must never become the committed default outside local development.
- Generated inventories must stay free of secrets and local-only credentials.
- `HTTP request completed` logs must stay payload-free: status, route template, duration, `request_id`, `trace_id`, `span_id`, and route/tool correlation ids are allowed; product payload belongs in product-turn logs, span attributes, or span events.
- Product content and arbitrary identifiers remain forbidden in metric labels.

Access
------

- Victoria and Grafana ports remain loopback-only; remote operators use an SSH tunnel.
- Grafana uses a dedicated operator credential.
- Victoria and OTEL endpoints must not be published as public APIs.
- Payload access is limited to product-quality, incident-response, and security operators.

Notes
-----

- The product-observability exception applies only to the internal Victoria stack. External model, embeddings, or observability providers require separate decisions.
