"""Command line entry point."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import typer
from rich.console import Console
from rich.markdown import Markdown

from code_agent import __version__
from code_agent.agents.chat import REPLY_KEY, ChatAgent
from code_agent.agents.collector import CollectorNode
from code_agent.agents.reporter import ReporterNode
from code_agent.agents.reviewer import ReviewerAgent
from code_agent.config import AgentConfig
from code_agent.errors import AgentError, ConfigError
from code_agent.llm import OpenAILLMClient
from code_agent.logging_setup import get_logger, setup_logging
from code_agent.memory import JSONMemory
from code_agent.message import AgentMessage
from code_agent.state import ReviewTask, WorkflowState
from code_agent.tools.builtin import build_default_registry
from code_agent.workflow import Workflow

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2

app = typer.Typer(
    name="code-agent",
    help="代码审查 Agent：读取代码、调用工具、输出结构化审查报告。",
    no_args_is_help=True,
    add_completion=False,
)

log = get_logger("cli")


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


@app.command()
def review(
    path: Path = typer.Argument(..., exists=True, help="待审查的文件或目录。"),
    glob: str = typer.Option("**/*.py", "--glob", help="目录模式下收集文件的 glob。"),
    max_files: int = typer.Option(20, "--max-files", min=1, help="最多审查的文件数。"),
    focus: str | None = typer.Option(None, "--focus", help="附加关注点，例如「并发安全」。"),
    out: Path | None = typer.Option(None, "--out", help="报告输出路径；默认打印到 stdout。"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出 DEBUG 日志。"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="仅输出 WARNING 及以上日志。"),
) -> None:
    """审查 PATH 下的代码，输出 Markdown 报告。"""
    out_console = Console()
    err_console = Console(stderr=True)

    if verbose and quiet:
        err_console.print("[red]--verbose 与 --quiet 不能同时使用[/red]")
        raise typer.Exit(EXIT_USAGE)

    setup_logging("DEBUG" if verbose else ("WARNING" if quiet else "INFO"))

    config = AgentConfig.from_env()
    state = WorkflowState(
        run_id=uuid4().hex[:12],
        task=ReviewTask(
            target=path,
            glob=glob,
            max_files=max_files,
            focus=focus,
            out=out,
        ),
    )
    memory = JSONMemory(token_budget=config.token_budget)

    try:
        llm = OpenAILLMClient(config)
        workflow = Workflow(
            [
                CollectorNode(),
                ReviewerAgent(llm, build_default_registry(), config, memory),
                ReporterNode(),
            ]
        )
        state = asyncio.run(workflow.run(state))
    except ConfigError as exc:
        err_console.print(f"[red]配置错误：[/red]{exc}")
        raise typer.Exit(EXIT_USAGE) from exc
    except AgentError as exc:
        err_console.print(f"[red]运行失败：[/red]{exc}")
        raise typer.Exit(EXIT_RUNTIME) from exc

    try:
        journal = memory.save(state)
        log.info("run journal saved", extra={"kv": {"path": str(journal), "run": state.run_id}})
    except OSError as exc:  # a missing journal must not lose the report
        err_console.print(f"[yellow]无法保存运行记录：[/yellow]{exc}")

    for warning in state.warnings:
        err_console.print(f"[yellow]警告：[/yellow]{warning}")

    markdown = state.artifacts.get("markdown")
    if state.status == "failed" or not markdown:
        err_console.print(f"[red]未产出报告：[/red]{state.error or 'unknown error'}")
        raise typer.Exit(EXIT_RUNTIME)

    if out is not None:
        out.write_text(markdown, encoding="utf-8")
        out_console.print(f"报告已写入 {out}")
    else:
        out_console.print(Markdown(markdown))
    raise typer.Exit(EXIT_OK)


@app.command()
def chat(
    path: Path = typer.Option(
        Path("."), "--path", "-p", exists=True, help="对话聚焦的代码根目录。"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出 DEBUG 日志。"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="仅输出 WARNING 及以上日志。"),
) -> None:
    """交互式多轮对话（跨轮记忆）；输入 exit / quit 或 Ctrl-D 退出。"""
    out_console = Console()
    err_console = Console(stderr=True)

    if verbose and quiet:
        err_console.print("[red]--verbose 与 --quiet 不能同时使用[/red]")
        raise typer.Exit(EXIT_USAGE)

    setup_logging("DEBUG" if verbose else ("WARNING" if quiet else "INFO"))

    config = AgentConfig.from_env()
    try:
        llm = OpenAILLMClient(config)
    except ConfigError as exc:
        err_console.print(f"[red]配置错误：[/red]{exc}")
        raise typer.Exit(EXIT_USAGE) from exc

    root = path.resolve()
    state = WorkflowState(run_id=uuid4().hex[:12], task=ReviewTask(target=root))
    agent = ChatAgent(llm, build_default_registry(), config, root)
    out_console.print(f"[dim]仓库根目录：{root}｜输入 exit 退出[/dim]")

    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            out_console.print()
            break

        text = line.strip()
        if not text:
            continue
        if text.lower() in {"exit", "quit", ":q"}:
            break

        state.messages.append(AgentMessage(id=uuid4().hex[:12], role="user", content=text))
        try:
            state = asyncio.run(agent.run(state))
        except ConfigError as exc:
            err_console.print(f"[red]配置错误：[/red]{exc}")
            raise typer.Exit(EXIT_USAGE) from exc
        except AgentError as exc:
            err_console.print(f"[red]本轮失败：[/red]{exc}")
            continue

        for warning in state.warnings:
            err_console.print(f"[yellow]警告：[/yellow]{warning}")
        state.warnings.clear()

        reply = state.artifacts.get(REPLY_KEY, "")
        if reply:
            out_console.print(Markdown(reply))
        else:
            err_console.print("[red]本轮没有得到回答。[/red]")

    raise typer.Exit(EXIT_OK)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址；默认仅本机可访问。"),
    port: int = typer.Option(8000, "--port", min=1, max=65535, help="监听端口。"),
) -> None:
    """启动本地 Web 界面（需先 pip install -e ".[web]"）。"""
    err_console = Console(stderr=True)
    try:
        import uvicorn
    except ImportError:
        err_console.print('[red]缺少 Web 依赖。请先运行：[/red]pip install -e ".[web]"')
        raise typer.Exit(EXIT_USAGE) from None

    from code_agent.web.app import create_app

    if not AgentConfig.from_env().api_key:
        err_console.print("[yellow]警告：未检测到 OPENAI_API_KEY，页面会提示缺少凭证。[/yellow]")

    Console().print(f"[dim]审查卷宗：http://{host}:{port}（Ctrl-C 停止）[/dim]")
    uvicorn.run(create_app(), host=host, port=port)
