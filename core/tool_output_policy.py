"""Shared runtime-vs-benchmark output policy for retrieval tools.

Runtime user responses must receive full-fidelity payloads in ``ToolResult.output``.
Bounded benchmark/debug artifacts belong in ``ToolResult.metadata`` only.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


RUNTIME_PAYLOAD_FORMAT_FULL_JSON = "full_json"


def serialize_runtime_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_output_contract_metadata(
    *,
    bench_artifact: dict[str, Any] | None = None,
    runtime_payload_format: str = RUNTIME_PAYLOAD_FORMAT_FULL_JSON,
    bench_payload_format: str = "",
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"runtime_payload_format": runtime_payload_format}
    if bench_payload_format:
        metadata["bench_payload_format"] = bench_payload_format
    if isinstance(bench_artifact, dict) and bench_artifact:
        metadata["bench_artifact"] = bench_artifact
    return metadata


def get_runtime_payload_format(metadata: Mapping[str, Any] | None) -> str:
    if not isinstance(metadata, Mapping):
        return ""
    return str(metadata.get("runtime_payload_format") or "")


def get_bench_payload_format(metadata: Mapping[str, Any] | None) -> str:
    if not isinstance(metadata, Mapping):
        return ""
    return str(metadata.get("bench_payload_format") or "")
