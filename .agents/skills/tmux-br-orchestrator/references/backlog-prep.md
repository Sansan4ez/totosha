# Backlog Preparation

Use this flow before starting the `tmux` orchestrator in a new repo.

## Goal

Create a `br` graph that is executable:

- issues exist;
- dependencies are explicit;
- acceptance criteria are visible in `br show`;
- `br ready` returns a sane starting set.

## Typical sources of work

- RFCs
- design docs
- migration plans
- GitHub issues
- Jira / Linear tickets
- manual engineering task lists

## Minimal issue quality bar

Each issue should include:

- a precise title;
- a description with scope;
- type and priority;
- a clear done condition;
- dependencies if the issue is not independently executable.

Bad:

```text
fix routing
```

Better:

```text
implement source-scoped KB route families and route-aware corp_db contract
```

## RFC -> `br` decomposition

A good default is:

1. one epic for the RFC rollout;
2. one issue per major implementation area;
3. one issue per validation/publish step if it can be run independently;
4. one issue per follow-up operational task if it has different ownership or runtime.

Example:

- RFC says "new routing catalog"
- create:
  - runtime route selection
  - published manifest generation
  - prompt/skill alignment
  - observability/smoke validation

## Minimal command flow

```bash
br create --title "routing rollout" --type epic --priority 1
br create --title "implement runtime route selection" --type feature --priority 1
br create --title "publish route manifests" --type task --priority 1
br create --title "update prompt and skill routing rules" --type task --priority 2
br create --title "add observability smoke for route selection" --type task --priority 2
```

Then connect dependencies:

```bash
br dep add publish-manifests implement-runtime-route-selection
br dep add update-prompts publish-manifests
br dep add observability-smoke publish-manifests
```

Replace the example ids with real issue ids.

## Before orchestration

Run:

```bash
br ready
br dep tree <epic-id>
```

Check:

1. at least one issue is ready;
2. the ready set makes architectural sense;
3. parallel candidates do not have overlapping write scopes;
4. issue descriptions are strong enough that `br show <id>` can drive a Codex worker.

Only after that should you start the `tmux` orchestrator.
