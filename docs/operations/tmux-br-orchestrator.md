tmux + br Orchestrator
======================

Purpose
-------

This pattern runs `br` tasks in `tmux` windows with `codex exec`, while preserving:

- dependency order from `br`;
- a hard cap on parallel work;
- file-scope safety between concurrent tasks;
- automatic cleanup after completion.

Why this works
--------------

`br` already answers the hard scheduling question: "what is unblocked now?".  
`tmux` already answers the hard runtime question: "how do I keep several long-running agents alive and observable?".

The orchestrator only needs to glue them together:

1. wait until a blocking issue is closed;
2. start the next ready issue in its own `tmux` window;
3. run `codex exec` with a narrow prompt and explicit scope;
4. repeat until the graph is complete.

Recommended rules
-----------------

- Use `br ready` or `br show <id>` as the source of truth for sequencing.
- Move an issue to `in_progress` before spawning its window.
- Do not run more than `2-3` Codex windows at once.
- Parallelize only tasks with disjoint write scopes.
- Keep one issue per window.
- Give each window a stable name such as `xjk-codex` or `wrn-codex`.
- Remove helper log files when the queue finishes if they duplicate Codex session logs.

Minimal shape
-------------

```bash
#!/usr/bin/env bash
set -euo pipefail

SESSION="totosha"
REPO="/home/admin/totosha"

is_closed() {
  br show "$1" | head -n1 | grep -q 'CLOSED'
}

wait_closed() {
  until is_closed "$1"; do
    sleep 30
  done
}

launch_issue() {
  local issue="$1"
  local window="$2"
  local prompt="$3"

  br update "$issue" --status=in_progress
  tmux new-window -t "$SESSION" -n "$window" \
    "cd $REPO && printf '%s\n' \"$prompt\" | codex exec --dangerously-bypass-approvals-and-sandbox -C $REPO -; exec bash"
}
```

Example with 5 tasks
--------------------

Assume this dependency graph:

- `task-a` has no blockers.
- `task-b` depends on `task-a`.
- `task-c` depends on `task-a`.
- `task-d` depends on `task-b`.
- `task-e` depends on both `task-c` and `task-d`.

One simple orchestrator can look like this:

```bash
#!/usr/bin/env bash
set -euo pipefail

SESSION="demo"
REPO="/home/admin/totosha"

is_closed() {
  br show "$1" | head -n1 | grep -q 'CLOSED'
}

wait_closed() {
  local issue="$1"
  until is_closed "$issue"; do
    echo "waiting for $issue"
    sleep 20
  done
}

launch_issue() {
  local issue="$1"
  local window="$2"
  local prompt="$3"
  br update "$issue" --status=in_progress
  tmux new-window -t "$SESSION" -n "$window" \
    "cd $REPO && printf '%s\n' \"$prompt\" | codex exec --dangerously-bypass-approvals-and-sandbox -C $REPO -; exec bash"
}

# 1. Start A.
launch_issue "task-a" "task-a" "Implement task-a, run focused verification, close the bead if complete."
wait_closed "task-a"

# 2. Start B and C in parallel.
launch_issue "task-b" "task-b" "Implement task-b only. Do not touch task-c files."
launch_issue "task-c" "task-c" "Implement task-c only. Do not touch task-b files."
wait_closed "task-b"

# 3. Start D after B.
launch_issue "task-d" "task-d" "Implement task-d after task-b. Avoid task-c files."
wait_closed "task-c"
wait_closed "task-d"

# 4. Start E after both C and D.
launch_issue "task-e" "task-e" "Implement task-e using the completed outputs of task-c and task-d."
wait_closed "task-e"
```

The key point is that the orchestrator does not need a full scheduler.  
For a small dependency graph, explicit `wait_closed -> launch_issue` phases are enough and easier to debug than a generic job runner.

Operational tips
----------------

- Inspect active windows:

```bash
tmux list-windows -t totosha
```

- Check the current ready queue:

```bash
br ready
```

- Inspect one issue:

```bash
br show totosha-xjk
```

- Jump into the orchestrator window:

```bash
tmux select-window -t totosha:br-orchestrator
```

- Kill a finished worker window:

```bash
tmux kill-window -t totosha:xjk-codex
```

When to use this pattern
------------------------

Use it when:

- the task graph is already modeled in `br`;
- each task can be expressed as a narrow Codex prompt;
- you want long-running work to survive terminal disconnects;
- you need controlled concurrency instead of ad hoc manual tab management.

Do not use it when:

- tasks have unclear or overlapping file ownership;
- the dependency graph changes every few minutes;
- one task must be manually supervised step by step.
