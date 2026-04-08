"""File operation tools"""

import sys
import os as os_module
sys.path.insert(0, os_module.path.dirname(os_module.path.dirname(os_module.path.abspath(__file__))))

import os
import re
import glob as globlib
import subprocess
import shutil
from security import is_sensitive_file
from logger import tool_logger
from models import ToolResult, ToolContext

DEFAULT_CORP_DOCS_ROOT = "/data/corp_docs"


def normalize_path(input_path: str, cwd: str) -> str:
    """Normalize path to user's workspace"""
    # Handle "workspace/..." -> "/workspace/..."
    if input_path.startswith("workspace/"):
        input_path = "/" + input_path
    
    if not input_path.startswith("/"):
        return os.path.join(cwd, input_path)
    
    # Fix common mistake: /workspace/file.txt -> /workspace/{userId}/file.txt
    match = re.match(r"/workspace/(\d+)", cwd)
    if match:
        user_id = match.group(1)
        if re.match(r"^/workspace/(?!\d+/)", input_path):
            fixed = input_path.replace("/workspace/", f"/workspace/{user_id}/")
            tool_logger.info(f"Auto-fixed path: {input_path} → {fixed}")
            return fixed
    
    return input_path


def _managed_document_roots() -> tuple[str, ...]:
    return tuple(
        os.path.realpath(path)
        for path in (os.getenv("CORP_DOCS_ROOT", DEFAULT_CORP_DOCS_ROOT),)
    )


def _is_within_root(resolved: str, root: str) -> bool:
    return resolved == root or resolved.startswith(root + os.sep)


def is_path_safe(path: str, cwd: str) -> tuple[bool, str]:
    """Check if path is within workspace or allowed directories"""
    resolved = os.path.realpath(path)
    resolved_cwd = os.path.realpath(cwd)

    for root in _managed_document_roots():
        if _is_within_root(resolved, root):
            return False, "Cannot access managed document corpus directly"

    # Allow reading from /data/skills/ (skills are read-only)
    if resolved.startswith("/data/skills") and (resolved == "/data/skills" or resolved.startswith("/data/skills/")):
        return True, ""

    if not resolved.startswith(resolved_cwd):
        return False, "Path outside workspace"

    # Block workspace root listing
    if resolved == "/workspace" or resolved == "/workspace/":
        return False, "Cannot access workspace root"

    # Block _shared folder
    if "/_shared" in resolved:
        return False, "Cannot access shared folder"

    return True, ""


def _glob_anchor(pattern: str, cwd: str) -> str:
    normalized = normalize_path(pattern or ".", cwd)
    magic_match = re.search(r"[*?\[]", normalized)
    if not magic_match:
        return normalized
    prefix = normalized[: magic_match.start()]
    if prefix.endswith(os.sep):
        anchor = prefix.rstrip(os.sep)
    else:
        anchor = os.path.dirname(prefix)
    return anchor or os.sep


async def tool_read_file(args: dict, ctx: ToolContext) -> ToolResult:
    """Read file contents"""
    path = normalize_path(args.get("path", ""), ctx.cwd)
    offset = args.get("offset")
    limit = args.get("limit")
    
    safe, reason = is_path_safe(path, ctx.cwd)
    if not safe:
        return ToolResult(False, error=f"🚫 {reason}")
    
    if is_sensitive_file(path):
        return ToolResult(False, error="🚫 Cannot read sensitive file")
    
    if not os.path.exists(path):
        return ToolResult(False, error=f"File not found: {path}")
    
    tool_logger.info(f"Reading: {path}")
    
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        
        if offset is not None or limit is not None:
            lines = content.split("\n")
            start = (offset or 1) - 1
            end = start + limit if limit else len(lines)
            content = "\n".join(f"{start + i + 1}|{l}" for i, l in enumerate(lines[start:end]))
        
        if len(content) > 100000:
            content = content[:100000] + "\n...(truncated)"
        
        return ToolResult(True, output=content or "(empty file)")
    except Exception as e:
        return ToolResult(False, error=str(e))


async def tool_write_file(args: dict, ctx: ToolContext) -> ToolResult:
    """Write content to file"""
    path = normalize_path(args.get("path", ""), ctx.cwd)
    content = args.get("content", "")
    
    safe, reason = is_path_safe(path, ctx.cwd)
    if not safe:
        return ToolResult(False, error=f"🚫 {reason}")
    
    if is_sensitive_file(path):
        return ToolResult(False, error="🚫 Cannot write sensitive file")
    
    tool_logger.info(f"Writing: {path} ({len(content)} bytes)")
    
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return ToolResult(True, output=f"Written {len(content)} bytes to {args['path']}")
    except Exception as e:
        return ToolResult(False, error=str(e))


async def tool_edit_file(args: dict, ctx: ToolContext) -> ToolResult:
    """Edit file by replacing text"""
    path = normalize_path(args.get("path", ""), ctx.cwd)
    old_text = args.get("old_text", "")
    new_text = args.get("new_text", "")
    
    safe, reason = is_path_safe(path, ctx.cwd)
    if not safe:
        return ToolResult(False, error=f"🚫 {reason}")
    
    if not os.path.exists(path):
        return ToolResult(False, error=f"File not found: {path}")
    
    tool_logger.info(f"Editing: {path}")
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        
        if old_text not in content:
            preview = content[:2000]
            return ToolResult(False, error=f"old_text not found.\n\nPreview:\n{preview}")
        
        new_content = content.replace(old_text, new_text, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        
        return ToolResult(True, output=f"Edited {args['path']}")
    except Exception as e:
        return ToolResult(False, error=str(e))


async def tool_delete_file(args: dict, ctx: ToolContext) -> ToolResult:
    """Delete file"""
    path = normalize_path(args.get("path", ""), ctx.cwd)
    
    safe, reason = is_path_safe(path, ctx.cwd)
    if not safe:
        return ToolResult(False, error=f"🚫 {reason}")
    
    if not os.path.exists(path):
        return ToolResult(False, error=f"File not found: {path}")
    
    tool_logger.info(f"Deleting: {path}")
    
    try:
        os.unlink(path)
        return ToolResult(True, output=f"Deleted: {args['path']}")
    except Exception as e:
        return ToolResult(False, error=str(e))


async def tool_search_files(args: dict, ctx: ToolContext) -> ToolResult:
    """Search files by glob pattern"""
    pattern = args.get("pattern", "")

    anchor = _glob_anchor(pattern, ctx.cwd)
    safe, reason = is_path_safe(anchor, ctx.cwd)
    if not safe:
        return ToolResult(False, error=f"🚫 {reason}")

    tool_logger.info(f"Searching files: {pattern}")

    try:
        normalized_pattern = normalize_path(pattern or ".", ctx.cwd)
        files = globlib.glob(normalized_pattern, recursive=True)
        # Filter out node_modules and .git
        files = [
            f for f in files
            if "node_modules" not in f
            and ".git" not in f
            and is_path_safe(f, ctx.cwd)[0]
        ]
        result = "\n".join(files[:200]) if files else "(no matches)"
        return ToolResult(True, output=result)
    except Exception as e:
        return ToolResult(False, error=str(e))


async def tool_search_text(args: dict, ctx: ToolContext) -> ToolResult:
    """Search text in files"""
    pattern = args.get("pattern", "")
    search_path = args.get("path", ctx.cwd)
    ignore_case = args.get("ignore_case", False)
    
    if not search_path.startswith("/"):
        search_path = os.path.join(ctx.cwd, search_path)

    safe, reason = is_path_safe(search_path, ctx.cwd)
    if not safe:
        return ToolResult(False, error=f"🚫 {reason}")
    
    tool_logger.info(f"Searching text: '{pattern}' in {search_path}")
    
    try:
        rg_path = shutil.which("rg")
        if rg_path:
            cmd = [
                rg_path,
                "-n",
                "--max-count",
                "200",
                "--glob",
                "!node_modules/**",
                "--glob",
                "!.git/**",
            ]
            if ignore_case:
                cmd.append("-i")
            cmd.extend([pattern, search_path])
        else:
            cmd = ["grep", "-rn", "--exclude-dir=node_modules", "--exclude-dir=.git"]
            if ignore_case:
                cmd.append("-i")
            cmd.extend([pattern, search_path])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        return ToolResult(True, output=(result.stdout or "").strip() or "(no matches)")
    except Exception as e:
        return ToolResult(True, output="(no matches)")


async def tool_list_directory(args: dict, ctx: ToolContext) -> ToolResult:
    """List directory contents"""
    path = args.get("path", ctx.cwd)
    if not path.startswith("/"):
        path = os.path.join(ctx.cwd, path)
    
    safe, reason = is_path_safe(path, ctx.cwd)
    if not safe:
        return ToolResult(False, error=f"🚫 {reason}")
    
    tool_logger.info(f"Listing: {path}")
    
    try:
        result = subprocess.run(f"ls -la '{path}'", shell=True, capture_output=True, text=True, timeout=10)
        return ToolResult(True, output=result.stdout or result.stderr)
    except Exception as e:
        return ToolResult(False, error=str(e))
