#!/usr/bin/env python3
"""Search corporate wiki Markdown files.

Default target is /home/clawdbot/clawd/wiki/ (Markdown files: **/*.md).
Outputs top N files by match count, with small context previews.

This search is intentionally **inexact** ("fuzzy"):
- The query is converted into a regex made of simple "stems" (prefixes) + "\\w*".
  Example: "контакты" -> "контак\\w*" and will match "контактная", "контакты", etc.
- Multiple words are joined with ".*" so the words can appear with other text between them.

Usage:
  wiki_search.py "поисковый запрос" [--path /path/to/file_or_dir] [--glob "**/*.md"]
                [--top 3] [--context 1] [--max-matches-per-file 5] [--ignore-case]
                [--link-style github|plain|file]

Notes:
- If --path is a file, searches that file only.
- If --path is a directory, searches files matching --glob (default: **/*.md).
- Prefers ripgrep (rg) for speed/robustness; falls back to Python regex search.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _default_wiki_path() -> Path:
    # 1) Explicit override (useful for deployments)
    env_path = os.environ.get("CORP_WIKI_PATH")
    if env_path:
        return Path(env_path)

    # 2) Totosha-friendly default: keep wiki content рядом со скиллом
    #    /data/skills/<skill>/scripts/wiki_search.py -> ../wiki
    skill_root = Path(__file__).resolve().parent.parent
    bundled = skill_root / "wiki"
    if bundled.exists():
        return bundled

    # 3) Legacy fallback (older deployments)
    return Path("/home/clawdbot/clawd/wiki")


DEFAULT_PATH = _default_wiki_path()


@dataclass
class Match:
    line_no: int
    line: str


@dataclass
class FileResult:
    path: Path
    matches: list[Match]
    total: int


def iter_files(path: Path, glob: str) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted([p for p in path.glob(glob) if p.is_file()])
    return []


_WORD_RE = re.compile(r"[\wА-Яа-яЁё]+", re.UNICODE)


def build_fuzzy_regex(query: str, *, unordered: bool = True) -> str:
    """Build an intentionally inexact regex for the query.

    - Each token becomes a "stem" prefix + "\\w*" to match different forms.
    - If unordered=True (default), tokens may appear in ANY order within a line.
      Implemented via lookaheads (requires PCRE2 for rg; Python fallback supports it).
    - If unordered=False, tokens must appear in the query order.
    """

    # Extract "words"; keep Unicode word chars (incl. Cyrillic) and digits.
    words = _WORD_RE.findall(query)
    if not words:
        return re.escape(query)

    parts: list[str] = []
    for w in words:
        w = w.strip("_-")
        if not w:
            continue

        # Tiny heuristic stemmer: use a prefix so different grammatical forms match.
        if len(w) <= 3:
            stem = w
        elif len(w) <= 6:
            stem = w[:4]
        else:
            stem = w[:5]

        parts.append(re.escape(stem) + r"\w*")

    if not parts:
        return re.escape(query)

    if unordered and len(parts) > 1:
        # Any order within a single line: all parts must be present.
        # Example: (?=.*контак\w*)(?=.*моск\w*).*
        return "".join([f"(?=.*{p})" for p in parts]) + r".*"

    # In-order: allow anything between tokens.
    return r".*".join(parts)


def preview(lines: list[str], line_no: int, context: int) -> list[tuple[int, str]]:
    start = max(1, line_no - context)
    end = min(len(lines), line_no + context)
    return [(ln, lines[ln - 1].rstrip("\n")) for ln in range(start, end + 1)]


def format_link(style: str, path: Path, line_no: int) -> str:
    """Return a human-friendly 'link' to a location in a file.

    Styles:
      - plain:  relative/path.md:123
      - github: relative/path.md#L123
      - file:   file:///abs/path.md#L123
    """
    rel = os.path.relpath(path, Path.cwd())
    if style == "plain":
        return f"{rel}:{line_no}"
    if style == "file":
        return f"file://{path.resolve()}#L{line_no}"
    return f"{rel}#L{line_no}"


def search_with_rg(
    query: str,
    path: Path,
    glob: str,
    ignore_case: bool,
) -> dict[Path, list[int]]:
    """Return mapping: file -> list of line numbers with matches."""
    rg = shutil.which("rg")
    if not rg:
        raise RuntimeError("rg not found")

    pattern = build_fuzzy_regex(query)

    cmd: list[str] = [
        rg,
        "--json",
        "--no-heading",
        "--line-number",
        "--pcre2",
        "--regexp",
        pattern,
    ]
    if ignore_case:
        cmd.append("--ignore-case")

    # When searching a directory, constrain by glob.
    if path.is_dir():
        cmd.extend(["--glob", glob, str(path)])
    else:
        cmd.append(str(path))

    # rg exit codes: 0 matches, 1 no matches, 2 error
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode == 2:
        raise RuntimeError(p.stderr.strip() or "rg failed")
    if p.returncode == 1:
        return {}

    hits: dict[Path, list[int]] = {}
    for line in p.stdout.splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "match":
            continue
        data = obj.get("data") or {}
        path_text = (((data.get("path") or {}).get("text")) or "").strip()
        ln = data.get("line_number")
        if not path_text or not isinstance(ln, int):
            continue
        fp = Path(path_text)
        hits.setdefault(fp, []).append(ln)

    # Keep stable order and de-dup line numbers.
    for fp in list(hits.keys()):
        uniq = sorted(set(hits[fp]))
        hits[fp] = uniq

    return hits


def iter_blocks(lines: list[str]) -> list[tuple[int, int, list[str]]]:
    """Split file into logical blocks (paragraph-ish).

    Block boundaries:
    - empty line
    - markdown heading line (starts with '#')

    Returns list of (start_line_no, end_line_no, block_lines).
    """
    blocks: list[tuple[int, int, list[str]]] = []
    cur: list[str] = []
    start_ln: int | None = None

    def flush(end_ln: int) -> None:
        nonlocal cur, start_ln
        if start_ln is None:
            cur = []
            return
        # drop trailing blank lines inside block
        while cur and cur[-1].strip() == "":
            cur.pop()
            end_ln -= 1
        if cur:
            blocks.append((start_ln, end_ln, cur))
        cur = []
        start_ln = None

    for i, line in enumerate(lines, start=1):
        is_blank = line.strip() == ""
        is_heading = bool(re.match(r"^\s*#", line))

        if is_heading and cur:
            flush(i - 1)

        if is_blank:
            if cur:
                flush(i - 1)
            continue

        if start_ln is None:
            start_ln = i
        cur.append(line)

    if cur:
        flush(len(lines))

    return blocks


def search_with_python(query: str, files: list[Path], ignore_case: bool) -> dict[Path, list[int]]:
    """Block-level fuzzy search.

    Returns mapping file -> list of *line numbers* to preview.
    A file is considered a hit if at least one block matches.

    We search across the whole block (DOTALL), then choose preview lines inside the
    block that match the line-level pattern.
    """
    flags = (re.IGNORECASE if ignore_case else 0) | re.DOTALL
    block_pattern = re.compile(build_fuzzy_regex(query, unordered=True), flags)
    line_pattern = re.compile(build_fuzzy_regex(query, unordered=True), re.IGNORECASE if ignore_case else 0)

    hits: dict[Path, list[int]] = {}

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        lines = text.splitlines(True)
        blocks = iter_blocks(lines)

        file_preview_lines: list[int] = []
        for start_ln, end_ln, blines in blocks:
            btxt = "".join(blines)
            if not block_pattern.search(btxt):
                continue

            # choose preview lines within this block
            # 1) prefer lines that match the full (unordered) line-level pattern
            # 2) additionally include lines matching ANY token stem (helps show e.g. "Телефон" inside "Москва" block)
            tokens = _WORD_RE.findall(query)
            token_res: list[re.Pattern[str]] = []
            for t in tokens:
                t = t.strip("_-")
                if not t:
                    continue
                if len(t) <= 3:
                    stem = t
                elif len(t) <= 6:
                    stem = t[:4]
                else:
                    stem = t[:5]
                token_res.append(re.compile(re.escape(stem) + r"\w*", re.IGNORECASE if ignore_case else 0))

            for off, l in enumerate(blines, start=0):
                ln = start_ln + off
                if line_pattern.search(l):
                    file_preview_lines.append(ln)
                    continue
                if any(tr.search(l) for tr in token_res):
                    file_preview_lines.append(ln)

            # Always include the start of the block for orientation.
            file_preview_lines.append(start_ln)

        if file_preview_lines:
            hits[f] = sorted(set(file_preview_lines))

    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="Search string")
    ap.add_argument("--path", default=str(DEFAULT_PATH), help="File or directory to search")
    ap.add_argument("--glob", default="**/*.md", help="Glob when --path is a directory")
    ap.add_argument("--top", type=int, default=3, help="Top files to show")
    ap.add_argument("--context", type=int, default=2, help="Lines before/after match (2 => 5 lines total)")
    ap.add_argument("--max-matches-per-file", type=int, default=5, help="Preview matches per file")
    ap.add_argument("--ignore-case", action="store_true", help="Case-insensitive search")
    ap.add_argument(
        "--link-style",
        choices=["github", "plain", "file"],
        default="github",
        help="How to format per-match location links",
    )

    args = ap.parse_args()

    path = Path(args.path)

    # Validate inputs early.
    if not path.exists():
        print(f"No files found for path={path}")
        return 2

    files = iter_files(path, args.glob)
    if not files:
        print(f"No files found for path={path}")
        return 2

    # For block-level matching we rely on Python. rg stays as a fast-path ONLY when
    # the query is a single token (it is safe to treat it line-wise).
    hits: dict[Path, list[int]]
    single_token = len(_WORD_RE.findall(args.query)) <= 1

    if single_token:
        try:
            hits = search_with_rg(args.query, path, args.glob, args.ignore_case)
        except Exception:
            hits = search_with_python(args.query, files, args.ignore_case)
    else:
        hits = search_with_python(args.query, files, args.ignore_case)

    if not hits:
        print("No matches.")
        return 1

    # Build results with line text.
    results: list[FileResult] = []
    for fp, line_nos in hits.items():
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        lines = text.splitlines(True)
        ms: list[Match] = []
        for ln in line_nos:
            if 1 <= ln <= len(lines):
                ms.append(Match(ln, lines[ln - 1].rstrip("\n")))
        if ms:
            results.append(FileResult(fp, ms, len(ms)))

    if not results:
        print("No matches.")
        return 1

    results.sort(key=lambda r: (r.total, -len(str(r.path))), reverse=True)

    top = results[: max(1, args.top)]

    for idx, r in enumerate(top, start=1):
        rel = os.path.relpath(r.path, Path.cwd())
        print(f"#{idx} {rel} — совпадений: {r.total}")

        try:
            text = r.path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            print("  [WARN] cannot re-read file for preview")
            print()
            continue
        lines = text.splitlines(True)

        shown = 0
        for m in r.matches:
            if shown >= args.max_matches_per_file:
                break
            link = format_link(args.link_style, r.path, m.line_no)
            ctx = preview(lines, m.line_no, args.context)
            start_ln = ctx[0][0]
            end_ln = ctx[-1][0]
            print(f"  - фрагмент {shown+1}: {link} (строки {start_ln}–{end_ln})")
            for ln, l in ctx:
                mark = ">" if ln == m.line_no else " "
                print(f"    {mark} {ln}: {l}")
            shown += 1
        if r.total > shown:
            print(f"  … ещё совпадений: {r.total - shown}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
