#!/usr/bin/env python3
"""Run pinned R700 conversational trials and preserve raw JSONL plus summaries.

This is an opt-in LLM evaluation tool, not a CI test: it requires an authorized Core
account and an operator-provided provider/model/config pin. Artifacts may contain
conversation text; choose a private output directory and redact before sharing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "bench/golden/r700-chain-regression.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--provider", required=True, help="Pinned provider identifier")
    parser.add_argument("--model", required=True, help="Exact configured and provider-returned model")
    parser.add_argument("--config-revision", required=True, help="Prompt/config revision identifier")
    parser.add_argument("--build-sha", required=True, help="Deployed container/build SHA")
    parser.add_argument("--sampling-config", required=True, help="Exact temperature/sampling configuration")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out-dir", required=True, help="Private directory for raw/summary artifacts")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--chat-id", type=int, required=True, help="Dedicated isolated test chat")
    parser.add_argument("--core-url", default="http://127.0.0.1:4000")
    parser.add_argument("--docker-exec", action="store_true")
    args = parser.parse_args()
    if args.runs < 10:
        parser.error("--runs must be at least 10")

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    pin = {
        "provider": args.provider,
        "model": args.model,
        "config_revision": args.config_revision,
        "sampling_config": args.sampling_config,
        "build_sha": args.build_sha,
        "source_sha": revision,
        "dataset": str(Path(args.dataset).resolve()),
        "runs": args.runs,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "chat_execution_mode": "runtime",
    }
    (out_dir / "pinned-config.json").write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")

    for index in range(1, args.runs + 1):
        raw = out_dir / f"run-{index:02d}.jsonl"
        summary = out_dir / f"run-{index:02d}-summary.json"
        command = [
            sys.executable, str(ROOT / "bench/bench_run.py"), "--dataset", args.dataset,
            "--out", str(raw), "--user-id", str(args.user_id), "--chat-id", str(args.chat_id),
            "--core-url", args.core_url, "--preserve-session", "--chat-execution-mode", "runtime",
            "--force-agent-chat", "--expected-configured-model", args.model, "--expected-llm-model", args.model,
        ]
        if args.docker_exec:
            command.append("--docker-exec")
        subprocess.run(command, cwd=ROOT, check=True)
        subprocess.run([
            sys.executable, str(ROOT / "bench/bench_eval.py"), "--dataset", args.dataset,
            "--results", str(raw), "--json-out", str(summary),
        ], cwd=ROOT, check=True)

    (out_dir / "run-manifest.json").write_text(json.dumps({
        **pin, "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "raw_files": [f"run-{i:02d}.jsonl" for i in range(1, args.runs + 1)],
        "summary_files": [f"run-{i:02d}-summary.json" for i in range(1, args.runs + 1)],
        "production_smoke_performed": False,
    }, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
