# CLAUDE.md

## 项目
实现一个代码审查 Agent，CLI 交互，支持 Agent 循环、工具调用、上下文记忆、错误重试。

## 技术栈
Python 3.11+，openai，pydantic，typer，rich，tenacity，pytest，ruff。
使用 src layout。

## 常用命令
ruff check .
pytest -q
python -m code_agent review examples/bad_code.py

## 规则
- 每次修改后必须运行 ruff check . 和 pytest -q。
- 小步提交，commit message 用 feat/fix/test/docs。
- 所有网络调用必须有超时、重试、错误处理。
- 工具返回 JSON 可序列化结果。
- 不要引入 LangChain/LlamaIndex，除非我明确同意。
- 不要做 Web，CLI 优先。
- 不要一次性重写整个仓库。