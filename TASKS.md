# TASKS.md — 项目1 执行清单

> 依据 `DESIGN.md`。**确认本文件后**按顺序执行。
> 每个任务的固定节奏：**写接口/测试 → 实现 → `ruff check .` → `pytest -q` → `git commit` → 汇报**。
> Commit 前缀：`feat` / `fix` / `test` / `docs`。小步提交，一任务一 commit（或少数几笔）。
> 每个任务完成即汇报：改了什么、验收命令输出、下一任务。

---

## Task 1 — 项目骨架与工具链
**产出**：`pyproject.toml`（依赖 openai/pydantic/typer/rich/tenacity；dev: pytest/pytest-asyncio/ruff；src layout）、`src/code_agent/{__init__,__main__}.py`、最小 `cli.py`（仅 `--help`/`--version`）、`examples/bad_code.py`、`README.md`、`.gitignore`、`tests/test_smoke.py`。
**关键**：目标解释器为本机 **Python 3.14.2**（已确认）。先 `pip install -e ".[dev]"`；仅当 wheel 缺失致安装失败时暂停并请你决策（不自行装解释器）。
**验收**：
```bash
pip install -e ".[dev]" && ruff check . && pytest -q && python -m code_agent --help
```
Commit：`feat: 项目骨架与 CLI 入口`

---

## Task 2 — 配置、错误类型、日志
**产出**：`config.py`（`AgentConfig`：`OPENAI_API_KEY`/`OPENAI_BASE_URL`/`CODE_AGENT_MODEL`、超时、`max_iterations`、`token_budget`）、`errors.py`（DESIGN §9 异常层级）、`logging_setup.py`（key=value Formatter，级别开关）。
**测试**：`test_config.py`（env 覆盖、缺 key 报 `ConfigError`）、`test_logging.py`（格式断言）。
**验收**：
```bash
ruff check . && pytest -q tests/test_config.py tests/test_logging.py
```
Commit：`feat: 配置、错误类型与结构化日志`

---

## Task 3 — 数据模型
**产出**：`message.py`（`AgentMessage`/`ToolCall` + `to_openai`）、`state.py`（`ReviewTask`/`UsageStats`/`TraceEvent`/`WorkflowState`）、`report.py` 的 schema 部分（`Finding`/`Severity`/`ReviewReport`）。
**测试**：`test_message_state.py`、`test_report.py`（序列化往返、`to_openai` 字段裁剪、severity 校验）。
**验收**：
```bash
ruff check . && pytest -q tests/test_message_state.py tests/test_report.py
```
Commit：`feat: 消息、状态与报告数据模型`

---

## Task 4 — LLM 客户端
**产出**：`llm.py`：`LLMClient`（AsyncOpenAI 封装）、`chat()`、超时、tenacity 重试与错误分类（§9）。定义可被 `FakeLLM` 替换的协议。
**测试**：`test_llm_client.py`：monkeypatch 造 429→成功（验证重试）、401→`ConfigError`（不重试）、超时→`LLMBusyError`、usage 解析。
**验收**：
```bash
ruff check . && pytest -q tests/test_llm_client.py
```
Commit：`feat: LLM 客户端（超时/重试/错误分类）`

---

## Task 5 — 工具注册表与内置工具
**产出**：`tools/registry.py`（`Tool`/`ToolRegistry`，schema 派生、按名调用、异常转 `{ok:false}`）、`tools/builtin.py`（`list_files`/`read_file`/`search_code`/`run_lint`）。
**测试**：`test_registry.py`（注册/查找/未知工具/异常包装）、`test_tools.py`（tmp_path 下读/搜/lint；大文件截断；二进制跳过；ruff 缺失降级）。
**验收**：
```bash
ruff check . && pytest -q tests/test_registry.py tests/test_tools.py
```
Commit：`feat: 工具注册表与 4 个内置工具`

---

## Task 6 — JSON 记忆
**产出**：`memory.py`：`JSONMemory` 落盘 `state` 子集到 `.code_agent/runs/<run_id>.json`、`load(run_id)`、`build_context(state)` 上下文裁剪（保 system、保 tool 配对、超预算摘要化）。
**测试**：`test_memory.py`（往返读写、裁剪后 tool_call/tool_result 配对完整、预算边界）。
**验收**：
```bash
ruff check . && pytest -q tests/test_memory.py
```
Commit：`feat: JSON 记忆与上下文裁剪`

---

## Task 7 — BaseAgent 循环
**产出**：`base_agent.py`：`run`/`_step`/`_execute_tools`/`_finalize`/`_degrade`，含守卫（`max_iterations`、token 预算）、无工具调用时的 nudge、终态工具识别。
**测试**：`test_agent_loop.py` 用 `FakeLLM` 脚本化：①工具→终态正常路径；②无工具调用→nudge 一次；③终态 args 非法→修复重试→部分报告；④循环耗尽→`_degrade`。
**验收**：
```bash
ruff check . && pytest -q tests/test_agent_loop.py
```
Commit：`feat: BaseAgent 循环与守卫`

---

## Task 8 — Node / Workflow 抽象
**产出**：`node.py`（`Node` 协议）、`workflow.py`（线性执行器，写 `state.node`、记 `node_start/node_end`、`failed` 短路）。含项目2 扩展缝的注释说明（不实现图调度）。
**测试**：`test_workflow.py`：顺序执行、状态透传、失败短路、trace 记录。
**验收**：
```bash
ruff check . && pytest -q tests/test_workflow.py
```
Commit：`feat: Node/Workflow 节点抽象（为项目2 预留）`

---

## Task 9 — 三个节点：Collector / Reviewer / Reporter
**产出**：`agents/collector.py`（无 LLM，按 glob 收集文件填 `state.files`）、`agents/reviewer.py`（`ReviewerAgent` + `prompts.py` + `submit_review` 终态 → 校验进 `state.report`，含 `_degrade` 部分报告）、`agents/reporter.py`（`report.py` 的 `render_markdown`）。
**测试**：`test_reviewer.py`（`FakeLLM` 端到端跑通三节点，产合法 `ReviewReport`；渲染含 summary/评分/findings 表格）。
**验收**：
```bash
ruff check . && pytest -q tests/test_reviewer.py
```
Commit：`feat: Collector/Reviewer/Reporter 三节点与 Markdown 渲染`

---

## Task 10 — CLI 集成与端到端
**产出**：`cli.py` 完整 `review` 命令（`--glob`/`--max-files`/`--focus`/`--out`/`--verbose`/`--quiet`），装配 `AgentConfig`→`LLMClient`→`ToolRegistry`→`Workflow([Collector, Reviewer, Reporter])`，rich 渲染到 stdout 或 `--out`，退出码映射（§9）。
**测试**：`test_cli.py`（`CliRunner` + FakeLLM：成功路径、`--out` 落盘、无 API key→退出码 2、`--help`）。
**验收**：
```bash
ruff check . && pytest -q
python -m code_agent review examples/bad_code.py --focus "并发与资源释放"
```
（最后一条需真实 `OPENAI_API_KEY`；无 key 时以 `--help` + 测试套件替代，并在汇报中说明未跑真实调用。）
Commit：`feat: CLI review 命令与端到端串联`

---

## 完成标准（DoD）
- `ruff check .` 无告警；`pytest -q` 全绿。
- `python -m code_agent review examples/bad_code.py` 产出 Markdown 报告（真实 key 可用时）。
- 三节点 Workflow 跑通，`WorkflowState` 全链路透传，`.code_agent/runs/<id>.json` 落盘。
- 每个任务一笔（或几笔）`feat/fix/test/docs` commit，历史清晰。
- 无 LangChain/LlamaIndex、无 Web、无向量库；工具数 = 5。
