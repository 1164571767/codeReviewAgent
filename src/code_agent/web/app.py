"""Local web UI for the code review agent.

Reuses the exact same :class:`~code_agent.workflow.Workflow` the CLI runs; the
browser receives a Server-Sent Events stream of trace events followed by the
final report. Nothing here duplicates agent logic.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from code_agent.agents.collector import CollectorNode
from code_agent.agents.reporter import ReporterNode
from code_agent.agents.reviewer import ReviewerAgent
from code_agent.config import AgentConfig
from code_agent.errors import AgentError, ConfigError
from code_agent.llm import OpenAILLMClient
from code_agent.state import ReviewTask, WorkflowState
from code_agent.tools.builtin import build_default_registry
from code_agent.workflow import Workflow

STATIC_DIR = Path(__file__).parent / "static"

LLMFactory = Callable[[AgentConfig], Any]


class ReviewRequest(BaseModel):
    path: str
    glob: str = "**/*.py"
    max_files: int = Field(default=20, ge=1, le=200)
    focus: str | None = None


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _done_frame(state: WorkflowState) -> dict[str, Any]:
    report = state.report
    return {
        "type": "done",
        "run_id": state.run_id,
        "status": state.status,
        "error": state.error,
        "warnings": list(state.warnings),
        "files": list(state.files),
        "usage": state.usage.model_dump(mode="json"),
        "model": report.model if report else "",
        "markdown": state.artifacts.get("markdown", ""),
        "report": report.model_dump(mode="json") if report else None,
    }


async def stream_review(
    request: ReviewRequest,
    config: AgentConfig,
    llm_factory: LLMFactory = OpenAILLMClient,
) -> AsyncIterator[str]:
    """Run one review, yielding SSE frames: ``start``, ``trace``*, ``done``|``error``."""
    state = WorkflowState(
        run_id=uuid4().hex[:12],
        task=ReviewTask(
            target=Path(request.path),
            glob=request.glob,
            max_files=request.max_files,
            focus=request.focus,
        ),
    )
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    state.set_event_sink(lambda event: queue.put_nowait(("trace", event)))

    async def runner() -> None:
        try:
            llm = llm_factory(config)
            workflow = Workflow(
                [
                    CollectorNode(),
                    ReviewerAgent(llm, build_default_registry(), config),
                    ReporterNode(),
                ]
            )
            queue.put_nowait(("done", await workflow.run(state)))
        except AgentError as exc:
            queue.put_nowait(("error", str(exc)))
        except Exception as exc:  # noqa: BLE001 - surfaced to the browser, not swallowed
            queue.put_nowait(("error", f"{type(exc).__name__}: {exc}"))

    task = asyncio.create_task(runner())
    yield _sse({"type": "start", "run_id": state.run_id})
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "trace":
                yield _sse({"type": "trace", "event": payload.model_dump(mode="json")})
            elif kind == "done":
                yield _sse(_done_frame(payload))
                break
            else:
                yield _sse({"type": "error", "message": payload})
                break
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def create_app() -> FastAPI:
    app = FastAPI(title="code-agent", docs_url=None, redoc_url=None)

    @app.get("/api/config")
    async def get_config() -> dict[str, Any]:
        config = AgentConfig.from_env()
        return {
            "model": config.model,
            "base_url": config.base_url or "https://api.openai.com/v1",
            "has_key": bool(config.api_key),
        }

    @app.post("/api/review")
    async def post_review(request: ReviewRequest) -> StreamingResponse:
        config = AgentConfig.from_env()
        try:
            config.require_api_key()
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return StreamingResponse(
            stream_review(request, config),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app
