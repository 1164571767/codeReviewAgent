"""Prompts for the reviewer agent."""

from __future__ import annotations

from collections.abc import Sequence

from code_agent.state import ReviewTask

REVIEWER_SYSTEM_PROMPT = """\
你是一名资深代码审查工程师。

工作方式：
1. 先用 list_files / search_code 定位可疑代码，再用 read_file 阅读上下文。
2. 用 run_lint 获取静态检查结果；工具返回 JSON，ok=false 表示该次调用失败，
   请根据 error 字段调整参数后重试，不要臆造工具结果。
3. 只报告你确实在代码中看到的问题，每条发现都要给出文件、行号与证据片段。
4. 调查结束后，调用 submit_review 提交结构化报告：summary、score(0-100)、
   files_reviewed、findings。findings 的 severity 取 info/low/medium/high/critical。

不要编造未读取过的文件内容。信息不足时宁可少报，也不猜测。
"""


def build_review_prompt(task: ReviewTask, files: Sequence[str]) -> str:
    lines = [f"审查目标：{task.target}", f"待审文件（{len(files)} 个）："]
    lines.extend(f"- {path}" for path in files)
    if task.focus:
        lines.append(f"重点关注：{task.focus}")
    lines.append("请调查后调用 submit_review 提交结构化审查报告。")
    return "\n".join(lines)
