"""Tests for the builtin tools (filesystem + ruff, all local)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from code_agent.tools import builtin
from code_agent.tools.builtin import list_files, read_file, run_lint, search_code


@pytest.fixture
def sample_tree(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("import os\nx = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    return tmp_path


def test_list_files_glob(sample_tree: Path) -> None:
    result = list_files(str(sample_tree), "**/*.py")
    assert result["ok"] is True
    assert result["count"] == 2
    assert all(name.endswith(".py") for name in result["files"])


def test_list_files_missing_path() -> None:
    assert list_files("does/not/exist").get("ok") is False


def test_list_files_limit_truncates(sample_tree: Path) -> None:
    result = list_files(str(sample_tree), "**/*.py", limit=1)
    assert result["truncated"] is True
    assert len(result["files"]) == 1


def test_read_file_full(sample_tree: Path) -> None:
    result = read_file(str(sample_tree / "pkg" / "a.py"))
    assert result["ok"] is True
    assert result["total_lines"] == 2
    assert "import os" in result["content"]


def test_read_file_line_range(sample_tree: Path) -> None:
    result = read_file(str(sample_tree / "pkg" / "a.py"), start=2, end=2)
    assert result["content"] == "x = 1"
    assert (result["start"], result["end"]) == (2, 2)


def test_read_file_missing() -> None:
    assert read_file("nope.py")["ok"] is False


def test_read_file_binary(tmp_path: Path) -> None:
    binary = tmp_path / "bin.dat"
    binary.write_bytes(b"\x00\x01\x02")
    assert read_file(str(binary))["ok"] is False


def test_read_file_truncates_large(tmp_path: Path) -> None:
    big = tmp_path / "big.py"
    big.write_text("x = 1\n" * 100, encoding="utf-8")
    result = read_file(str(big), max_bytes=10)
    assert result["truncated"] is True


def test_search_code_matches(sample_tree: Path) -> None:
    result = search_code(r"import os", str(sample_tree))
    assert result["ok"] is True
    assert result["count"] == 1
    assert result["matches"][0]["line"] == 1


def test_search_code_bad_regex(sample_tree: Path) -> None:
    result = search_code("(unclosed", str(sample_tree))
    assert result["ok"] is False


def test_search_code_limit(sample_tree: Path) -> None:
    result = search_code(r"=\s*\d", str(sample_tree), limit=1)
    assert result["truncated"] is True
    assert result["count"] == 1


def test_run_lint_reports_issues(tmp_path: Path) -> None:
    target = tmp_path / "lintme.py"
    target.write_text("import os\n", encoding="utf-8")
    result = run_lint(str(target))
    assert result["ok"] is True
    assert result["count"] >= 1
    assert any(issue["code"] == "F401" for issue in result["issues"])


def test_run_lint_clean_file(tmp_path: Path) -> None:
    target = tmp_path / "clean.py"
    target.write_text("x = 1\n", encoding="utf-8")
    result = run_lint(str(target))
    assert result["ok"] is True
    assert result["count"] == 0


def test_run_lint_missing_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(builtin.shutil, "which", lambda _name: None)

    def _no_ruff(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError

    monkeypatch.setattr(builtin.subprocess, "run", _no_ruff)
    result = run_lint(str(tmp_path))
    assert result["ok"] is False
    assert "not installed" in result["error"]


def test_run_lint_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="ruff", timeout=1)

    monkeypatch.setattr(builtin.subprocess, "run", _timeout)
    result = run_lint(str(tmp_path))
    assert result["ok"] is False
    assert "timed out" in result["error"]
