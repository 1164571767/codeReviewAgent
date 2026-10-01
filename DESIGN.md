# DESIGN.md — 代码审查 Agent（项目1）

> 状态：待确认。确认后按 `TASKS.md` 顺序执行。
> 目标：CLI 代码审查 Agent。输入代码路径 → Agent 循环调用工具（读/搜/lint）→ LLM 产出结构化审查报告 → 渲染 Markdown。
> 约束：架构必须为项目2（多 Agent Workflow）预留**节点能力**；不过度设计（CLI、工具 ≤5、记忆用 JSON、无向量库）。

---

## 1. 选型

| 领域 | 选择 | 理由 | 被否方案 |
|---|---|---|---|
| 语言 | Python 3.14（本机 3.14.2，唯一可用解释器） | 已确认以本机版本开发；`X \| None`、`tomllib` 等 | 3.11/3.12（本机未安装） |
| 包管理 | `pyproject.toml` + setuptools，src layout | 需求指定 src layout；`pip install -e ".[dev]"` 可编辑安装 | poetry（多余一层） |
| LLM SDK | `openai`（AsyncOpenAI） | 需求指定；`base_url` 可指向 DeepSeek/兼容端点 | 自研 HTTP（无谓轮子） |
| 数据模型 | `pydantic` v2 | 校验 + JSON 序列化 + 由模型直接生成 tool schema | dataclasses（无校验/无 schema 导出） |
| CLI | `typer` + `rich` | 需求指定；typer 生成 `--help`，rich 渲染 Markdown/表格 | argparse（啰嗦）、click 裸用 |
| 重试 | `tenacity` | 需求指定；指数退避 + 抖动，声明式 | 手写 while（易错） |
| 测试 | `pytest` + `pytest-asyncio` | 需求指定；async 循环需要 asyncio 测试 | — |
| Lint | `ruff` | 需求指定；同时作为 `run_lint` 工具的后端 | — |
| 日志 | 标准库 `logging` + 自定义 Formatter | 不引入 structlog 等额外依赖；key=value 单行可 grep | structlog（新依赖） |

**循环模型**：全链路 `async`（`LLMClient.chat` / `BaseAgent.run` / `Node.run` / `Workflow.run`）。理由：项目2 需要并行节点与并发工具调用。代价：`pytest-asyncio`。

**结构化输出**：使用 **function/tool calling**（终态工具 `submit_review`），**不依赖** OpenAI 私有 `response_format=json_schema`。理由：要兼容 DeepSeek 等端点。机型输出解析失败时有「修复提示重试」与「部分报告兜底」两级降级（见 §7）。

**依赖清单**：运行时 `openai`, `pydantic`, `typer`, `rich`, `tenacity`；开发时 `pytest`, `pytest-asyncio`, `ruff`。

> 环境：本机唯一解释器为 Python 3.14.2，**已确认以其开发**。`pip install -e ".[dev]"` 需 `pydantic-core` 提供 cp314 wheel（pydantic ≥2.12 支持）。若安装失败，暂停并请你决策——我不会自行安装解释器。

---

## 2. 目录结构

```
codeReviewAgent/
├── pyproject.toml
├── CLAUDE.md
├── DESIGN.md
├── TASKS.md
├── README.md
├── examples/
│   └── bad_code.py              # 演示用含瑕疵代码
├── src/
│   └── code_agent/
│       ├── __init__.py
│       ├── __main__.py          # python -m code_agent 入口
│       ├── cli.py               # typer app：review / --help / 参数
│       ├── config.py            # AgentConfig：env 读取、base_url、超时、预算
│       ├── errors.py            # 异常层级
│       ├── logging_setup.py     # key=value Formatter + 级别配置
│       ├── llm.py               # LLMClient（AsyncOpenAI 封装 + 超时 + tenacity 重试 + 错误分类）
│       ├── message.py           # AgentMessage / ToolCall
│       ├── state.py             # WorkflowState / ReviewTask / UsageStats / TraceEvent
│       ├── memory.py            # JSONMemory：落盘 + 上下文裁剪
│       ├── node.py              # Node 协议
│       ├── workflow.py          # Workflow：线性执行器（唯一知道拓扑的地方）
│       ├── base_agent.py        # BaseAgent(Node)：Agent 循环
│       ├── prompts.py           # Reviewer 系统提示词
│       ├── report.py            # ReviewReport / Finding / render_markdown
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── registry.py      # Tool / ToolRegistry
│       │   └── builtin.py       # list_files / read_file / search_code / run_lint
│       └── agents/
│           ├── __init__.py
│           ├── collector.py     # CollectorNode（无 LLM）
│           ├── reviewer.py      # ReviewerAgent(BaseAgent)
│           └── reporter.py      # ReporterNode（校验 + 渲染）
└── tests/
    ├── conftest.py              # FakeLLM、tmp 代码夹具、deterministic id/clock
    ├── test_config.py
    ├── test_logging.py
    ├── test_message_state.py
    ├── test_report.py
    ├── test_llm_client.py
    ├── test_registry.py
    ├── test_tools.py
    ├── test_memory.py
    ├── test_agent_loop.py
    ├── test_workflow.py
    ├── test_reviewer.py
    └── test_cli.py
```

**项目1 流水线**：`CollectorNode → ReviewerAgent → ReporterNode`，由 `Workflow` 线性驱动。

---

## 3. 为项目2 预留的节点能力（核心抽象）

两个契约，项目1 与项目2 共用：

```python
# node.py
class Node(Protocol):
    name: ClassVar[str]
    async def run(self, state: WorkflowState) -> WorkflowState: ...
```

```python
# workflow.py
class Workflow:
    """唯一知道拓扑的地方。项目1 用线性 for；项目2 替换调度即可，节点无感。"""
    def __init__(self, nodes: Sequence[Node]) -> None: ...
    async def run(self, state: WorkflowState) -> WorkflowState:
        for node in self.nodes:
            state.node = node.name
            log(event="node_start", node=node.name)
            state = await node.run(state)
            log(event="node_end", node=node.name)
            if state.status == "failed":
                break
        return state
```

**为什么这样就够预留**：
- 节点之间**不互相引用**，只通过 `WorkflowState`（共享状态）通信 → 加密边、条件跳转、fan-out 都是 `Workflow` 内的拓扑改动。
- `state.artifacts` 是节点间载荷通道；`state.messages` 是 Agent 会话通道，二者分离，项目2 多 Agent 各持自己的 messages 时不会互相污染。
- 项目2 扩展点（现在**不实现**，只留缝）：`Workflow` 换成基于 `edges: dict[str, list[Edge]]` 的调度器；`Edge` 带条件函数 `Callable[[WorkflowState], bool]`；并行节点用 `asyncio.gather`（接口已是 async）。
- `WorkflowState` 可 JSON 序列化 → 项目2 的检查点/断点续跑直接复用。

---

## 4. BaseAgent 接口

```python
# base_agent.py
class BaseAgent(Node, ABC):
    name: ClassVar[str]
    system_prompt: str                 # 子类提供
    finish_tool: ClassVar[str | None] = None   # 终态工具名，如 "submit_review"

    def __init__(self, llm: LLMClient, tools: ToolRegistry, config: AgentConfig) -> None: ...

    async def run(self, state: WorkflowState) -> WorkflowState:
        """Node 协议实现：播种 system 消息 → 进入 Agent 循环 → 收尾写 state。"""

    async def _step(self, state: WorkflowState) -> AgentMessage:
        """单轮 LLM：用 memory.build_context(state) 组上下文 + tools.schemas() 调用 LLM，返回 assistant 消息。"""

    async def _execute_tools(self, state: WorkflowState, calls: list[ToolCall]) -> list[AgentMessage]:
        """并发执行工具调用，捕获异常转成 role=tool 的 JSON 结果消息，记录 trace 与 usage。"""

    @abstractmethod
    async def _finalize(self, state: WorkflowState, args: dict[str, Any]) -> WorkflowState:
        """终态工具回调：把 args 校验进 state.report 等。"""
```

**职责边界**：`BaseAgent` 只管「循环 + 工具调度 + 消息累积 + 守卫」；**不**知道具体业务。项目2 的多 Agent 都是它的子类。

---

## 5. WorkflowState 字段

共享可变状态（pydantic，可序列化）。节点修改并返回同一对象。

```python
class ReviewTask(BaseModel):
    target: Path                      # 待审查文件或目录
    glob: str = "**/*.py"
    max_files: int = 20
    focus: str | None = None          # 用户附加关注点，如「只看并发安全」
    out: Path | None = None           # 报告输出路径

class UsageStats(BaseModel):
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0

class TraceEvent(BaseModel):
    ts: datetime
    node: str
    event: str                        # llm_request/llm_response/tool_call/tool_result/retry/...
    ok: bool = True
    dur_ms: int | None = None
    data: dict[str, Any] = {}

class WorkflowState(BaseModel):
    run_id: str
    task: ReviewTask
    status: Literal["pending", "running", "done", "failed"] = "pending"
    node: str | None = None                    # 当前节点（Workflow 维护）
    files: list[str] = []                      # Collector 产出：待审文件清单
    messages: list[AgentMessage] = []          # Agent 会话（短期上下文）
    findings: list[Finding] = []               # 累积发现
    report: ReviewReport | None = None         # 终态报告
    artifacts: dict[str, Any] = {}             # 节点间载荷（项目2 扩展通道）
    usage: UsageStats = UsageStats()
    trace: list[TraceEvent] = []
    warnings: list[str] = []                   # 降级/跳过类警告（非致命）
    error: str | None = None                   # 致命错误摘要
```

**记忆分两层**：
- 短期 = `state.messages`（Agent 会话，循环内使用）。
- 长期 = `JSONMemory` 落盘 `state` 的可序列化子集到 `.code_agent/runs/<run_id>.json`，供回溯/续跑；**无向量库**。

---

## 6. AgentMessage 字段

```python
Role = Literal["system", "user", "assistant", "tool"]

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]           # 已 json 解析；解析失败由 ToolCall 层兜成 {}

class AgentMessage(BaseModel):
    id: str
    role: Role
    content: str | None = None
    name: str | None = None             # role=tool 时为工具名
    tool_call_id: str | None = None     # role=tool 时回填
    tool_calls: list[ToolCall] = []     # role=assistant 且请求工具时
    created_at: datetime
    meta: dict[str, Any] = {}           # node / model / latency_ms / tokens

    def to_openai(self) -> dict[str, Any]:
        """转 openai chat 格式，剔除内部字段（created_at/meta）。"""
```

---

## 7. ReviewReport schema

```python
class Severity(str, Enum):
    info = "info"; low = "low"; medium = "medium"; high = "high"; critical = "critical"

class Finding(BaseModel):
    id: str                             # 稳定 id，如 F-001
    severity: Severity
    category: str                       # bug / security / style / perf / maintainability
    file: str
    line: int | None = None
    title: str
    detail: str
    suggestion: str | None = None
    evidence: str | None = None         # 代码片段

class ReviewReport(BaseModel):
    summary: str                        # 总体结论
    score: int = Field(ge=0, le=100)    # 质量分
    files_reviewed: list[str]
    findings: list[Finding]
    generated_at: datetime
    model: str
    usage: UsageStats
```

`submit_review` 工具的入参 JSON schema 由 `ReviewReport.model_json_schema()` 派生（去掉 `generated_at/model/usage` 等运行期字段，由 `_finalize` 回填）。终态校验失败 → 降级链（见 §8）。

---

## 8. Agent 循环伪代码

```
async def BaseAgent.run(state):
    if not has_system(state.messages):
        state.messages.append(system(self.system_prompt))
    nudged = False
    for it in range(config.max_iterations):            # 默认 12
        if state.usage.total_tokens() > config.token_budget:
            state.warnings.append("token budget exceeded"); break

        ctx = memory.build_context(state)              # 按预算裁剪历史
        resp = await llm.chat(ctx, tools=tools.schemas(), temperature=config.temperature)
        #   llm.chat 内部：超时 + tenacity 重试 + 错误分类（见 §9）
        msg = to_agent_message(resp)
        state.messages.append(msg)
        state.usage.llm_calls += 1; state.usage += resp.usage
        trace(event="llm_response", it=it, tool_calls=len(msg.tool_calls))

        if not msg.tool_calls:                         # 模型没要工具
            if nudged: break                           # 已提醒过一次 → 结束
            state.messages.append(user("请调用 submit_review 提交结构化结果。"))
            nudged = True; continue

        if self.finish_tool in {c.name for c in msg.tool_calls}:
            args = call_for(self.finish_tool).arguments
            return await self._finalize(state, args)   # 终态

        results = await self._execute_tools(state, msg.tool_calls)  # 并发
        state.messages.extend(results)
    # 循环耗尽 / 预算超限
    return await self._degrade(state, reason="max_iterations")
```

**上下文裁剪（`memory.build_context`）**：始终保留 `system`；从尾部保留最近消息直到接近预算；中间被裁掉的 `tool` 结果替换为一行摘要（`[omitted N chars ok=true]`），保证 tool_call ↔ tool_result 配对不被拆散。

**工具集（4 调查工具 + 1 终态工具 = 5，未超限）**：

| 工具 | 入参 | 返回（JSON 可序列化） |
|---|---|---|
| `list_files` | `path, glob, limit` | `{ok, files: [...]}` |
| `read_file` | `path, start?, end?` | `{ok, path, start, end, content}` |
| `search_code` | `pattern, path, glob` | `{ok, matches: [{file, line, text}]}` |
| `run_lint` | `path` | `{ok, issues: [{file, line, code, message}]}`（ruff `--output-format json`） |
| `submit_review` | ReviewReport 子集 | 终态，不返回内容 |

所有工具**不抛异常给循环**：内部异常一律转 `{ok: false, error: "..."}` 交给模型自行恢复。

---

## 9. 错误处理

**异常层级**（`errors.py`）：

```
AgentError(Exception)
├── ConfigError            配置/鉴权/参数问题（不重试）
├── LLMError
│   ├── LLMBusyError       限流/超时/5xx 重试后仍失败
│   └── LLMResponseError   响应结构不可解析
├── ToolError              工具内部错误（默认被工具吞成 JSON）
├── ReviewError            终态报告生成失败
└── MaxIterationsExceeded  循环守卫
```

**策略表**：

| 失败情形 | 处理 | 重试 |
|---|---|---|
| LLM 超时 / 429 / 5xx | tenacity：指数退避 + 抖动，最多 4 次 | ✅ |
| LLM 401/403/404 | 立即 `ConfigError`，退出码 2 | ❌ |
| 工具参数 JSON 坏 | 兜成 `{}`，工具返回 `{ok:false}` 让模型改正 | 循环内 |
| 工具运行时报错（文件缺失、ruff 未装） | 转 `{ok:false, error}` 入消息；ruff 缺失记 `warnings`，Agent 继续 | 循环内 |
| 终态 args 不符合 ReviewReport | 追加修复 user 消息重试，最多 2 次；仍失败 → `_degrade` 用已累积 `findings` 组**部分报告** | 2 次 |
| `max_iterations` / token 预算耗尽 | `_degrade`：有 findings 则产部分报告 + warning；无则 `failed` | ❌ |
| 报告写盘失败 | 传播，退出码 1 | ❌ |

**退出码**：`0` 成功；`1` 运行期错误（LLM/工具/写盘致命）；`2` 配置/用法错误。所有致命错误：stderr 打 `ERROR`，已落盘 run journal 路径一并打印。

---

## 10. 日志格式

- **日志 → stderr**（可 grep），**报告 → stdout 或 `--out` 文件**，两者分流。
- 格式：单行 `key=value`，时间 ISO8601 UTC 毫秒。
- 级别：`DEBUG` 内部细节 / `INFO` 里程碑 / `WARNING` 可恢复 / `ERROR` 致命。`--verbose`→DEBUG，`--quiet`→WARNING。

```
ts=2026-10-01T22:10:00.123Z level=INFO run=8f3a node=ReviewerAgent iter=2 event=tool_call tool=read_file ok=true dur_ms=12
ts=2026-10-01T22:10:00.456Z level=WARNING run=8f3a node=ReviewerAgent event=tool_result tool=run_lint ok=false err="ruff not found"
```

事件名：`run_start, node_start, node_end, llm_request, llm_response, retry, tool_call, tool_result, memory_save, report_ready, run_end`。

---

## 11. 测试策略（全程无网络）

- `FakeLLM`：实现与 `LLMClient` 相同协议，脚本化返回序列（如：`read_file` 调用 → `submit_review`），驱动确定性循环测试。
- 工具：`tmp_path` 建临时代码文件验证，含边界（超大文件截断、二进制跳过、ruff 缺失）。
- CLI：`typer.testing.CliRunner` + 注入 `FakeLLM`。
- 确定性：注入 `id_factory` 和固定 `clock`，避免 `run_id`/时间戳抖动。

## 12. 已知风险

1. **Python 3.14 wheel**：已选定 3.14；仅当 pydantic-core 无 cp314 wheel 致安装失败时暂停并请你决策（不自行装解释器）。
2. **端点不支持并行 tool calls**：`_execute_tools` 按序执行即可，不影响正确性。
3. **兼容端点 tool calling 质量差**：靠修复重试 + 部分报告兜底，不硬失败。
4. **上下文裁剪丢证据**：裁剪优先保 `tool_result`，仅当超预算才摘要化。
