#!/usr/bin/env bash
set -euo pipefail

OUTPUT=""
SESSION="work"
REPO="$(pwd)"

usage() {
  cat <<'EOF'
Usage:
  init-orchestrator.sh --output /path/to/orchestrator.sh [--session tmux-session] [--repo /path/to/repo]

Writes a starter tmux + br orchestrator script with placeholder phases.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      OUTPUT="${2:-}"
      shift 2
      ;;
    --session)
      SESSION="${2:-}"
      shift 2
      ;;
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$OUTPUT" ]]; then
  echo "--output is required" >&2
  usage >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"

cat >"$OUTPUT" <<EOF
#!/usr/bin/env bash
set -euo pipefail

SESSION="$SESSION"
REPO="$REPO"

run_br() {
  local attempt=0
  while true; do
    if "\$@"; then
      return 0
    fi
    attempt=\$((attempt + 1))
    if (( attempt >= 8 )); then
      echo "br command failed after retries: \$*" >&2
      return 1
    fi
    sleep 2
  done
}

is_closed() {
  local line
  line="\$(br show "\$1" 2>/dev/null | head -n1 || true)"
  grep -q 'CLOSED' <<<"\$line"
}

wait_closed() {
  local issue="\$1"
  until is_closed "\$issue"; do
    echo "waiting for \$issue"
    sleep 30
  done
}

prompt_for_issue() {
  local issue="\$1"
  cat <<PROMPT
You are running in repo \$REPO.

Primary task: implement br issue \\\`\$issue\\\`.

First:
- Read \\\`AGENTS.md\\\`.
- Run \\\`br show \$issue\\\`.

Execution requirements:
- Stay within the issue scope from \\\`br show\\\`.
- Do not revert unrelated changes.
- Run focused verification.
- If complete:
  br close \$issue --reason "Implemented"
  br sync --flush-only
PROMPT
}

launch_issue() {
  local issue="\$1"
  local window="\$2"
  local buffer="\${issue}_prompt"

  run_br br update "\$issue" --status=in_progress
  tmux set-buffer -b "\$buffer" -- "\$(prompt_for_issue "\$issue")"
  tmux new-window -t "\$SESSION" -n "\$window" "cd \$REPO && tmux save-buffer -b \$buffer - | codex exec --dangerously-bypass-approvals-and-sandbox -C \$REPO -; exec bash"
}

# Replace these placeholders with your actual phases.
# Example:
# launch_issue "task-a" "task-a-codex"
# wait_closed "task-a"
# launch_issue "task-b" "task-b-codex"
# launch_issue "task-c" "task-c-codex"

echo "Edit this file and fill in your phases before running it."
EOF

chmod +x "$OUTPUT"
echo "Wrote starter orchestrator to $OUTPUT"
