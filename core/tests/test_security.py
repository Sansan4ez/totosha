from pathlib import Path

import pytest

import security


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/workspace/1/private.key", True),
        ("/workspace/1/server.pem", True),
        ("/workspace/1/certificate.p12", True),
        ("/workspace/1/certificate.pfx", True),
        ("/workspace/1/truststore.jks", True),
        ("/workspace/1/app.keystore", True),
        ("/workspace/1/.env", True),
        ("/workspace/1/.env.staging", True),
        ("/workspace/1/credentials.json", True),
        ("/workspace/1/.npmrc", True),
        ("/workspace/1/notes.md", False),
        ("/workspace/1/my.sshnotes", False),
        ("/workspace/1/.envoy", False),
        ("/workspace/1/run/secrets_backup/api_key", False),
        ("/home/u/.ssh/id_rsa", True),
        ("/home/u/.gnupg/pubring.kbx", True),
        ("/run/secrets/api_key", True),
    ],
)
def test_is_sensitive_file_classifies_names_suffixes_and_path_components(path, expected):
    assert security.is_sensitive_file(path) is expected


def test_is_sensitive_file_resolves_symlink_target(tmp_path):
    link = tmp_path / "notes.txt"
    link.symlink_to("/run/secrets/api_key")

    assert security.is_sensitive_file(str(link)) is True


def test_sanitize_output_redacts_supported_secret_formats():
    secrets = [
        "sk-12345678901234567890",
        "ghp_123456789012345678901234567890123456",
        "12345678:abcdefghijklmnopqrstuvwxyzABCDEFGHI",
        "Bearer abcdefghijklmnopqrst",
        "FOO_API_KEY=supersecret",
    ]
    output = "\n".join(secrets)

    sanitized = security.sanitize_output(output)

    assert sanitized == "\n".join(["[REDACTED]"] * len(secrets))
    assert all(secret not in sanitized for secret in secrets)


def test_sanitize_output_preserves_ordinary_text():
    output = "Build completed. Read notes.md and retry in 20 seconds."

    assert security.sanitize_output(output) == output


def test_check_command_blocks_matching_blocked_pattern(monkeypatch):
    monkeypatch.setattr(
        security,
        "BLOCKED_PATTERNS",
        [{"pattern": r"\bforbidden\b", "reason": "Forbidden command"}],
    )

    assert security.check_command("run forbidden now") == (
        False,
        True,
        "Forbidden command",
    )


def test_check_command_honors_admin_bypass(monkeypatch):
    monkeypatch.setattr(
        security,
        "BLOCKED_PATTERNS",
        [
            {
                "pattern": r"\bforbidden\b",
                "reason": "Forbidden command",
                "admin_bypass": True,
            }
        ],
    )

    assert security.check_command("run forbidden now", is_admin=True) == (
        False,
        False,
        "",
    )


@pytest.mark.parametrize(
    ("chat_type", "expected"),
    [
        ("group", (False, True, "BLOCKED in groups: Recursive delete")),
        ("private", (True, False, "Recursive delete")),
    ],
)
def test_check_command_handles_dangerous_command_by_chat_type(monkeypatch, chat_type, expected):
    monkeypatch.setattr(security, "BLOCKED_PATTERNS", [])

    assert security.check_command("rm -rf /tmp/example", chat_type=chat_type) == expected
