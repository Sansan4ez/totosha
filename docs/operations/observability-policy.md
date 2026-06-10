Observability Policy
====================

Purpose
-------

Define the repository policy for sampling, retention, cardinality, and sensitive-data handling.

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

Cardinality
-----------

- Do not place request ids, user ids, random UUIDs, prompt text, or raw URLs into metric labels.
- Prefer low-cardinality operational labels such as status, service name, route template, and error class.
- `request_id`, `trace_id`, and `span_id` may appear in logs and traces for correlation.
- Shared request metrics must keep labels limited to `service`, `method`, `route`, and `status`.
- Dedicated retrieval metrics may add bounded route/tool labels such as `selected_route_id`, `selected_route_kind`, `selected_source`, `knowledge_route_id`, `document_id`, and `tool_name` when those identifiers come from the published routing catalog or canonical tool set.

Sensitive Data
--------------

- Metrics, logs, and traces must not contain secrets, tokens, credentials, or raw private payloads.
- Temporary debug logging with sensitive content must never become the committed default.
- Generated inventories must stay free of secrets and local-only credentials.
- `HTTP request completed` logs must stay payload-free: status, route template, duration, `request_id`, `trace_id`, `span_id`, and route/tool correlation ids are allowed; user prompts and raw request bodies are not.

Notes
-----

- Keep any repo-specific exceptions short and explicit.
