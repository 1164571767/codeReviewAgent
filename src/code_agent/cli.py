"""Command line entry point."""

from __future__ import annotations

import typer

from code_agent import __version__

app = typer.Typer(
    name="code-agent",
    help="代码审查 Agent：读取代码、调用工具、输出结构化审查报告。",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"code-agent {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        help="显示版本并退出。",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """代码审查 Agent CLI。"""
