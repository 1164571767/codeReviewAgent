"""Smoke tests for the CLI skeleton."""

from __future__ import annotations

from typer.testing import CliRunner

from code_agent import __version__
from code_agent.cli import app

runner = CliRunner()


def test_help_lists_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "代码审查" in result.stdout


def test_version_option() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
