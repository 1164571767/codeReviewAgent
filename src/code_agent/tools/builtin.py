"""The four investigation tools used by the reviewer agent.

Each returns a JSON-serialisable dict with an ``ok`` flag. None of them raise.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from code_agent.tools.registry import Tool, ToolRegistry, ToolResult

MAX_READ_BYTES = 100_000
LINT_TIMEOUT = 60


def list_files(path: str = ".", glob: str = "**/*.py", limit: int = 200) -> ToolResult:
    root = Path(path)
    if not root.exists():
        return {"ok": False, "error": f"path not found: {path}"}
    if root.is_file():
        files = [str(root)]
    else:
        files = sorted(str(p) for p in root.glob(glob) if p.is_file())
    truncated = len(files) > limit
    return {
        "ok": True,
        "count": min(len(files), limit),
        "truncated": truncated,
        "files": files[:limit],
    }


def read_file(
    path: str,
    start: int | None = None,
    end: int | None = None,
    max_bytes: int = MAX_READ_BYTES,
) -> ToolResult:
    target = Path(path)
    if not target.is_file():
        return {"ok": False, "error": f"not a file: {path}"}
    try:
        data = target.read_bytes()
    except OSError as exc:
        return {"ok": False, "error": f"cannot read {path}: {exc}"}
    if b"\x00" in data[:1024]:
        return {"ok": False, "error": f"binary file: {path}"}

    byte_truncated = len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    lines = text.splitlines()
    first = 1 if start is None else max(1, start)
    last = len(lines) if end is None else min(end, len(lines))
    return {
        "ok": True,
        "path": str(target),
        "start": first,
        "end": last,
        "total_lines": len(lines),
        "truncated": byte_truncated,
        "content": "\n".join(lines[first - 1 : last]),
    }


def search_code(
    pattern: str,
    path: str = ".",
    glob: str = "**/*.py",
    limit: int = 100,
) -> ToolResult:
    root = Path(path)
    if not root.exists():
        return {"ok": False, "error": f"path not found: {path}"}
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return {"ok": False, "error": f"bad regex: {exc}"}

    files = [root] if root.is_file() else sorted(root.glob(glob))
    matches: list[dict[str, Any]] = []
    for candidate in files:
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append({"file": str(candidate), "line": lineno, "text": line.strip()[:200]})
                if len(matches) >= limit:
                    return {
                        "ok": True,
                        "count": len(matches),
                        "truncated": True,
                        "matches": matches,
                    }
    return {"ok": True, "count": len(matches), "truncated": False, "matches": matches}


def run_lint(path: str = ".") -> ToolResult:
    exe = shutil.which("ruff")
    base = [exe] if exe else [sys.executable, "-m", "ruff"]
    command = [*base, "check", "--output-format", "json", path]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=LINT_TIMEOUT)
    except FileNotFoundError:
        return {"ok": False, "error": "ruff is not installed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"ruff timed out after {LINT_TIMEOUT}s"}

    # ruff exits 0 (clean) or 1 (issues found); anything else is a real failure.
    if proc.returncode not in (0, 1):
        return {"ok": False, "error": proc.stderr.strip() or f"ruff exited {proc.returncode}"}
    try:
        raw = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return {"ok": False, "error": "unparseable ruff output"}

    issues = [
        {
            "file": item.get("filename"),
            "line": (item.get("location") or {}).get("row"),
            "code": item.get("code"),
            "message": item.get("message"),
        }
        for item in raw
    ]
    return {"ok": True, "count": len(issues), "issues": issues}


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def build_default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(
                name="list_files",
                description="List files under a path matching a glob pattern.",
                parameters=_object(
                    {
                        "path": {"type": "string", "description": "File or directory to scan."},
                        "glob": {"type": "string", "description": "Glob pattern, e.g. **/*.py"},
                        "limit": {"type": "integer", "description": "Maximum files to return."},
                    },
                    ["path"],
                ),
                func=list_files,
            ),
            Tool(
                name="read_file",
                description="Read a text file, optionally a 1-based line range.",
                parameters=_object(
                    {
                        "path": {"type": "string"},
                        "start": {"type": "integer", "description": "First line (1-based)."},
                        "end": {"type": "integer", "description": "Last line (inclusive)."},
                    },
                    ["path"],
                ),
                func=read_file,
            ),
            Tool(
                name="search_code",
                description="Regex-search lines across files; returns file/line/text.",
                parameters=_object(
                    {
                        "pattern": {"type": "string", "description": "Python regex."},
                        "path": {"type": "string"},
                        "glob": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    ["pattern"],
                ),
                func=search_code,
            ),
            Tool(
                name="run_lint",
                description="Run ruff on a path and return structured issues.",
                parameters=_object({"path": {"type": "string"}}, ["path"]),
                func=run_lint,
            ),
        ]
    )
