#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import struct
import urllib.error
import urllib.request
import uuid
import wave
from io import BytesIO
from typing import Any


DEFAULT_PROXY_URL = "http://127.0.0.1:3200/transcribe"
DEFAULT_MGMT_URL = "http://127.0.0.1:8317/v0/management/transcribe-health"
EXPECTED_BRANCH = "feature/chatgpt-transcribe-endpoint"
EXPECTED_BACKEND_MODE = "chatgpt_compat"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ASR compatibility-path smoke for proxy -> CLIProxyAPI /transcribe.")
    parser.add_argument("--proxy-url", default=DEFAULT_PROXY_URL, help="Proxy /transcribe URL")
    parser.add_argument("--mgmt-url", default=DEFAULT_MGMT_URL, help="CLIProxyAPI transcribe-health endpoint")
    parser.add_argument("--mgmt-key", default=os.getenv("CLIPROXY_MGMT_KEY", ""), help="Bearer token for management endpoints")
    parser.add_argument("--timeout-s", type=float, default=30.0, help="Timeout for HTTP calls")
    parser.add_argument("--max-challenge-rate-5m", type=float, default=0.20, help="Fail when challenge rate in last 5m exceeds this value")
    parser.add_argument("--max-error-rate-5m", type=float, default=0.30, help="Fail when error rate in last 5m exceeds this value")
    parser.add_argument("--max-challenge-rate-30m", type=float, default=0.10, help="Fail when challenge rate in last 30m exceeds this value")
    parser.add_argument("--max-error-rate-30m", type=float, default=0.20, help="Fail when error rate in last 30m exceeds this value")
    parser.add_argument("--max-degraded-credentials", type=int, default=0, help="Fail when more degraded credentials are present")
    parser.add_argument("--skip-management", action="store_true", help="Skip transcribe-health threshold checks")
    parser.add_argument("--skip-proxy-smoke", action="store_true", help="Skip live POST /transcribe smoke")
    parser.add_argument("--json", action="store_true", help="Print JSON summary only")
    return parser.parse_args()


def http_json(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout_s: float,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            text = response.read().decode("utf-8")
            return int(getattr(response, "status", 200)), json.loads(text or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"error": raw[:500]}
        return int(exc.code), payload


def build_test_wav_bytes(*, sample_rate: int = 16_000, duration_s: float = 1.0, amplitude: int = 8_000, frequency_hz: float = 440.0) -> bytes:
    frames = int(sample_rate * duration_s)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        payload = bytearray()
        for index in range(frames):
            sample = int(amplitude * math.sin(2 * math.pi * frequency_hz * index / sample_rate))
            payload.extend(struct.pack("<h", sample))
        wav.writeframes(bytes(payload))
    return buffer.getvalue()


def build_multipart_body(*, field_name: str, filename: str, content_type: str, data: bytes) -> tuple[bytes, str]:
    boundary = f"----incident-asr-{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, boundary


def rate_for_window(window: dict[str, Any], numerator_key: str) -> float:
    requests = int(window.get("requests") or 0)
    if requests <= 0:
        return 0.0
    return float(window.get(numerator_key) or 0) / float(requests)


def validate_transcribe_health(
    payload: dict[str, Any],
    *,
    max_challenge_rate_5m: float,
    max_error_rate_5m: float,
    max_challenge_rate_30m: float,
    max_error_rate_30m: float,
    max_degraded_credentials: int,
) -> list[str]:
    errors: list[str] = []
    if payload.get("backend_mode") != EXPECTED_BACKEND_MODE:
        errors.append(f"backend_mode={payload.get('backend_mode')}")
    if payload.get("compatibility_branch") != EXPECTED_BRANCH:
        errors.append(f"compatibility_branch={payload.get('compatibility_branch')}")

    degraded = int(payload.get("degraded_credential_count") or 0)
    if degraded > max_degraded_credentials:
        errors.append(f"degraded_credential_count={degraded}")

    for label, window, max_challenge_rate, max_error_rate in (
        ("last_5m", payload.get("last_5m") or {}, max_challenge_rate_5m, max_error_rate_5m),
        ("last_30m", payload.get("last_30m") or {}, max_challenge_rate_30m, max_error_rate_30m),
    ):
        if not isinstance(window, dict):
            errors.append(f"{label}=missing")
            continue
        challenge_rate = rate_for_window(window, "challenges")
        error_rate = rate_for_window(window, "failures")
        if challenge_rate > max_challenge_rate:
            errors.append(f"{label}.challenge_rate={challenge_rate:.3f}")
        if error_rate > max_error_rate:
            errors.append(f"{label}.error_rate={error_rate:.3f}")
    return errors


def run_proxy_smoke(proxy_url: str, timeout_s: float) -> tuple[dict[str, Any], list[str]]:
    body, boundary = build_multipart_body(
        field_name="file",
        filename="incident-smoke.wav",
        content_type="audio/wav",
        data=build_test_wav_bytes(),
    )
    status, payload = http_json(
        proxy_url,
        method="POST",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout_s=timeout_s,
    )
    errors: list[str] = []
    if status != 200:
        errors.append(f"proxy_status={status}")
    transcript = str(payload.get("text") or "").strip()
    if status == 200 and not transcript:
        errors.append("proxy_response_missing_text")
    return {"http_status": status, "payload": payload}, errors


def print_summary(summary: dict[str, Any], errors: list[str], *, json_only: bool) -> None:
    if json_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    print("asr compatibility smoke")
    if "management" in summary:
        management = summary["management"]
        print(
            "- management: "
            f"backend_mode={management.get('backend_mode')} degraded={management.get('degraded_credential_count')}"
        )
    if "proxy_smoke" in summary:
        print(f"- proxy_smoke_http_status: {summary['proxy_smoke'].get('http_status')}")
    if errors:
        print("- failures:")
        for item in errors:
            print(f"  - {item}")
    else:
        print("- status: ok")


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    summary: dict[str, Any] = {"passed": False}

    if not args.skip_management:
        if not args.mgmt_key.strip():
            errors.append("missing_mgmt_key")
        else:
            status, payload = http_json(
                args.mgmt_url,
                headers={"Authorization": f"Bearer {args.mgmt_key.strip()}"},
                timeout_s=args.timeout_s,
            )
            summary["management_http_status"] = status
            summary["management"] = payload
            if status != 200:
                errors.append(f"management_status={status}")
            else:
                errors.extend(
                    validate_transcribe_health(
                        payload,
                        max_challenge_rate_5m=args.max_challenge_rate_5m,
                        max_error_rate_5m=args.max_error_rate_5m,
                        max_challenge_rate_30m=args.max_challenge_rate_30m,
                        max_error_rate_30m=args.max_error_rate_30m,
                        max_degraded_credentials=args.max_degraded_credentials,
                    )
                )

    if not args.skip_proxy_smoke:
        proxy_summary, proxy_errors = run_proxy_smoke(args.proxy_url, args.timeout_s)
        summary["proxy_smoke"] = proxy_summary
        errors.extend(proxy_errors)

    summary["passed"] = not errors
    print_summary(summary, errors, json_only=bool(args.json))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
