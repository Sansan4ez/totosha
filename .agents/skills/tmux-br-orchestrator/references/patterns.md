# Patterns

## Generic prompt builder

Use one shared template and inject the issue id:

```bash
build_prompt() {
  local issue="$1"
  cat <<EOF
You are running in repo $REPO.

Primary task: implement br issue \`$issue\`.

First:
- Read \`AGENTS.md\`.
- Run \`br show $issue\`.

Execution requirements:
- Use \`br show\` as the source of truth for scope and acceptance criteria.
- Make the code changes.
- Run focused verification.
- If complete:
  br close $issue --reason "Implemented"
  br sync --flush-only
EOF
}
```

## Semi-automatic prompt builder

Keep a short per-issue scope hint and reuse one template:

```bash
scope_hint() {
  case "$1" in
    totosha-wrn) echo "Focus on db/search_docs.py and indexing tests." ;;
    totosha-pbo) echo "Focus on runtime routing catalog and manifests." ;;
    totosha-rjv) echo "Focus on doc-worker build/runtime and operator commands." ;;
    *) echo "" ;;
  esac
}
```

Then append it into `build_prompt`.

## Five-task phase example

Graph:

- `task-a` has no blockers
- `task-b` depends on `task-a`
- `task-c` depends on `task-a`
- `task-d` depends on `task-b`
- `task-e` depends on `task-c` and `task-d`

Execution plan:

1. run `task-a`
2. run `task-b` and `task-c` in parallel
3. run `task-d`
4. run `task-e`

This is usually better than building a dynamic scheduler.

## Safe parallelism checklist

Parallelize only when all answers are "yes":

1. Do the tasks have different primary write scopes?
2. Can each task succeed without waiting for the other task's code changes?
3. Will their prompts make ownership explicit?
4. Will total active windows remain at `<= 3`?

If any answer is "no", keep the phase sequential.
