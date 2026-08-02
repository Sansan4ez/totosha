import importlib.util
import sys
import types
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "files.py"
_SPEC = importlib.util.spec_from_file_location("path_safety_files_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_saved_modules = {name: sys.modules.get(name) for name in ("security", "logger", "models")}
try:
    sys.modules["security"] = types.SimpleNamespace(is_sensitive_file=lambda path: False)
    sys.modules["logger"] = types.SimpleNamespace(
        tool_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None)
    )
    sys.modules["models"] = types.SimpleNamespace(
        ToolResult=object,
        ToolContext=object,
    )
    _SPEC.loader.exec_module(_MODULE)
finally:
    for name, original in _saved_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original

is_path_safe = _MODULE.is_path_safe


@pytest.mark.parametrize(
    ("cwd", "target", "expected"),
    [
        ("/workspace/1", "/workspace/1001/SESSION.json", False),
        ("/workspace/1", "/workspace/1007/MEMORY.md", False),
        ("/workspace/1", "/workspace/1/notes.md", True),
        ("/workspace/1", "/workspace/1/sub/notes.md", True),
        ("/workspace/990001", "/workspace/990002/x", False),
        ("/workspace/1", "/workspace", False),
    ],
)
def test_workspace_path_boundary(cwd, target, expected):
    safe, _ = is_path_safe(target, cwd)

    assert safe is expected


def test_symlink_to_another_workspace_is_rejected(tmp_path):
    workspace = tmp_path / "workspace"
    own_workspace = workspace / "1"
    other_workspace = workspace / "1001"
    own_workspace.mkdir(parents=True)
    other_workspace.mkdir()
    (own_workspace / "other-user").symlink_to(other_workspace, target_is_directory=True)

    safe, reason = is_path_safe(str(own_workspace / "other-user" / "SESSION.json"), str(own_workspace))

    assert safe is False
    assert reason == "Path outside workspace"


def test_shared_check_matches_path_component_only(tmp_path):
    workspace = tmp_path / "workspace" / "1"
    workspace.mkdir(parents=True)

    safe_backup, _ = is_path_safe(str(workspace / "a" / "_shared_backup" / "notes.md"), str(workspace))
    safe_shared, reason = is_path_safe(str(workspace / "a" / "_shared" / "notes.md"), str(workspace))

    assert safe_backup is True
    assert safe_shared is False
    assert reason == "Cannot access shared folder"
