---
name: tmux-br-orchestrator
description: Plan and run `br`/beads_rust issue graphs in separate `tmux` windows with `codex exec`, bounded parallelism, per-issue prompts, and dependency-safe orchestration. Use when a repo tracks work in `br` and you need to execute ready tasks across multiple long-running Codex agents while respecting dependencies and avoiding overlapping write scopes.
---

# tmux + br Orchestrator

Use this skill when work is already modeled in `br` and the main problem is execution order, safe parallelism, and durable long-running Codex sessions.

## Tooling context

`br` is the CLI for [`beads_rust`](https://github.com/Dicklesworthstone/beads_rust), the issue/dependency tracker used by the project. Treat `br` as the source of truth for:

- current ready work via `br ready`;
- issue scope and acceptance criteria via `br show <id>`;
- dependency structure via `br dep tree <id>`;
- exported issue state via `br sync --flush-only`.

## Prerequisites

Do not use this skill until all of the following are true:

- `br` is installed and works in the repo.
- `tmux` is installed.
- `codex` is installed and authenticated.
- the current working directory is the repository root.
- the repository has a usable `AGENTS.md` or equivalent local instructions.
- the backlog already exists in `br`, or you are ready to create it first.

This skill orchestrates execution. It does not invent backlog structure by itself.

## Where `br` tasks come from

In a new repo, issues in `br` usually come from one of four sources:

- manual issue creation with `br create`;
- decomposition of RFCs, design docs, or implementation plans;
- import or manual mirroring from an external tracker such as GitHub, Jira, or Linear;
- follow-up issues discovered during implementation.

The important constraint is simple: before orchestration starts, the work graph must already exist in `br` with usable descriptions and dependencies.

If the repo does not yet have a backlog, read [references/backlog-prep.md](references/backlog-prep.md) first.

## Workflow

1. Prepare the backlog if needed.
   If `br ready` is empty because the graph does not exist yet, create the issues first. Do not start with `tmux`.

2. Inspect the graph.
   Run `br ready`, `br show <id>`, and `br dep tree <epic-or-root>` to identify the ready set and the blocking chain.

3. Build phases, not a generic scheduler.
   Prefer explicit phases like:
   - wait for `xjk`
   - run `wrn` + `pbo`
   - run `rjv` + `sj7`
   - run `8yw`
   This is easier to debug than dynamic queue logic.

4. Parallelize only disjoint write scopes.
   Safe examples:
   - indexing task + routing-catalog task
   - doc-worker runtime task + prompt/skill task
   Unsafe examples:
   - two tasks editing `core/agent.py`
   - routing task + transport task both touching `core/tools/`
   Cap parallel Codex windows at `2-3`.

5. Keep one issue per `tmux` window.
   Use stable names like `xjk-codex`, `wrn-codex`, `oir-codex`.

6. Use `br` for state, not for prompt text.
   `br` provides status, dependencies, and acceptance criteria.
   The orchestrator provides the operational prompt:
   - read `AGENTS.md`
   - run `br show <id>`
   - stay within scope
   - run focused verification
   - if complete: `br close <id> --reason "Implemented"` and `br sync --flush-only`

7. Pass prompts through `tmux` buffer or stdin.
   This keeps quoting simpler than embedding large prompts directly in `tmux new-window`.

8. Clean up after completion.
   Kill finished worker windows and remove helper log files if they only duplicate Codex session logs.

## Backlog rules

Before execution, each `br` issue should have at least:

- a clear title;
- a meaningful description;
- issue type and priority;
- acceptance criteria or completion signal;
- explicit dependencies when order matters.

For design-heavy repos, derive issues from RFCs or plans:

- create one implementation issue per major deliverable;
- create separate issues for tasks that can be validated independently;
- add dependencies with `br dep add <issue> <depends-on>`;
- only orchestrate after `br ready` returns a sensible starting set.

Do not use the orchestrator to compensate for a vague backlog.

For a concrete preparation flow, read [references/backlog-prep.md](references/backlog-prep.md).

## Prompt Pattern

Use a shared prompt template plus a short per-issue scope hint. Keep the issue description in `br`, not in the orchestrator.

Minimal prompt shape:

```text
You are running in repo /path/to/repo.

Primary task: implement br issue `issue-id`.

First:
- Read `AGENTS.md`.
- Run `br show issue-id`.

Execution requirements:
- Stay within the issue scope from `br show`.
- Do not revert unrelated changes.
- Run focused verification.
- If complete:
  br close issue-id --reason "Implemented"
  br sync --flush-only
```

If the task needs tighter boundaries, add one short scope hint such as:
- `Focus on db/search_docs.py and indexing tests.`
- `Avoid observability-only changes.`

For more patterns, read [references/patterns.md](references/patterns.md).

## Launch Pattern

Use `tmux set-buffer` plus `codex exec`:

```bash
prompt="$(build_prompt totosha-xjk)"
tmux set-buffer -b xjk_prompt -- "$prompt"
tmux new-window -t totosha -n xjk-codex \
  "cd /repo && tmux save-buffer -b xjk_prompt - | codex exec --dangerously-bypass-approvals-and-sandbox -C /repo -; exec bash"
```

Preferred helper functions:
- `run_br`: retry `br` commands when the database is briefly busy
- `is_closed`: inspect `br show <id>` first line
- `wait_closed`: poll until the blocking task is closed
- `launch_issue`: mark `in_progress`, prepare prompt, open the `tmux` window

## Starter Script

If you need a new starter orchestrator, run:

```bash
./scripts/init-orchestrator.sh --output /tmp/br-orchestrator.sh --session mysession --repo /path/to/repo
```

This writes a generic shell skeleton with:
- `run_br`
- `is_closed`
- `wait_closed`
- `prompt_for_issue`
- `launch_issue`
- placeholder phases to fill in

## Operational Checks

- Inspect windows: `tmux list-windows -t <session>`
- Watch one worker: `tmux capture-pane -pt <session>:xjk-codex | tail -80`
- Check queue: `br ready`
- Inspect one issue: `br show <id>`

## Failure Rules

- If two tasks plausibly touch the same files, do not parallelize them.
- If an issue is still `in_progress`, do not start its dependents even if your inferred graph says they should be ready.
- If the worker closed the issue in `br` but the `tmux` process still exists, treat the issue as complete and clean up the window.
- If the issue cannot be completed, leave it `in_progress` or return it to `open` only if the workflow in that repo explicitly expects that.
- If a worker hangs, inspect its window, capture the pane, decide whether to interrupt or kill the window, and only then restart the issue.
- If tests fail but the issue is still actionable, keep the task open and re-run it with a narrower prompt rather than launching dependents.
- If the repository is dirty before orchestration starts, treat that as an explicit risk and avoid parallel windows until file ownership is clear.
