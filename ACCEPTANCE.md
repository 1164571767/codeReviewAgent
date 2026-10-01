# ACCEPTANCE.md — 本地真实环境验收

> 面向**你本人**在本机跑一次真实 LLM 调用的验收手册。
> 自动化测试（`pytest -q`，91 passed）全部用 `FakeLLM`、不联网；本文档补的是**真实端点**下的验收。
> 本文档不含任何密钥，可以安全提交到 GitHub。

---

## 0. 适用范围

- 验收对象：`python -m code_agent review` 的真实端到端行为。
- 样本：`examples/bad_code.py`（故意埋了 6 类缺陷）。
- 产物：Markdown 报告（stdout 或 `--out`）+ 运行记录 `.code_agent/runs/<run_id>.json`。

---

## 1. 前置条件

```bash
cd D:/codeReviewAgent
pip install -e ".[dev]"          # 已装过则跳过
python -m ruff --version         # run_lint 工具依赖 ruff
python -m code_agent --version   # 应输出 code-agent 0.1.0
```

要求：能访问你的 LLM 端点（官方或兼容端点）。

---

## 2. API Key 怎么注入

密钥**从不写进代码**，`config.py` 只从环境变量读。仓库里出现的 `sk-test` / `sk-abc` 全是 `tests/` 下的假值。

### 方式 A —— 环境变量（**当前仓库即支持**）

bash（你当前用的 shell，仅本终端有效）：

```bash
export OPENAI_API_KEY=sk-你的真实key

# 可选：走 OpenAI 兼容端点（DeepSeek 等），三者要配套
export OPENAI_BASE_URL=https://api.deepseek.com/v1
export CODE_AGENT_MODEL=deepseek-chat
```

PowerShell 仅本会话：`$env:OPENAI_API_KEY="sk-..."`

想要持久化（**写入的是用户级环境变量，不是仓库**，新开终端生效）：

```bash
setx OPENAI_API_KEY "sk-你的真实key"
```

反向验证：

```bash
python -c "import os;print('SET' if os.environ.get('OPENAI_API_KEY') else 'MISSING')"
```

### 方式 B —— `.env` 文件（**当前未启用，需先加 `python-dotenv`**）

⚠️ 现在把 key 写进 `.env` **无效**：`config.py` 没有加载 `.env`，只有 `os.environ`。
`.gitignore` 已忽略 `.env`，所以文件本身不会被提交——但读不到。

若要启用，需要我做两件事：
1. `pyproject.toml` 加依赖 `python-dotenv`，`config.py` 里在 `from_env()` 前调用 `load_dotenv()`；
2. 提交一份 `.env.example` 占位模板（不含真实值）。

届时用法：

```bash
cp .env.example .env      # 然后编辑 .env 填真实 key
```

`.env.example` 内容（提交版，纯占位）：

```
OPENAI_API_KEY=sk-your-key-here
# OPENAI_BASE_URL=https://api.deepseek.com/v1
# CODE_AGENT_MODEL=deepseek-chat
```

**优先级**：`load_dotenv()` 默认**不覆盖**已存在的环境变量，所以「环境变量 > `.env`」。CI/临时改 key 时 export 即可压过 `.env`。

### 密钥安全的硬性约束

- `.env`、`.code_agent/`、`.claude/`、`*.egg-info/` 均在 `.gitignore` 内，不会上传。
- 永远不要把 key 写进 `pyproject.toml` / 源码 / 测试 / commit message。
- 提交前自查：`git ls-files | grep -iE "\.env|key|secret"` 应无输出。
- 万一误提交：立刻在服务商后台**吊销该 key**，再 `git rm --cached` 并改写历史——吊销永远优先于清理历史。

---

## 3. 验收命令

```bash
export OPENAI_API_KEY=sk-...

# 主验收：真实调用一次
python -m code_agent review examples/bad_code.py --focus "并发与资源释放"; echo "exit=$?"

# 想留档：
python -m code_agent review examples/bad_code.py --out report.md
```

排障时加 `-v` 看 stderr 上的 `key=value` 日志（不污染 stdout 的报告）：

```bash
python -m code_agent review examples/bad_code.py -v
```

---

## 4. 达到什么效果算成功

### 4.1 硬性判据（全部满足才算通过）

| # | 判据 | 检查方式 |
|---|---|---|
| 1 | **退出码 0** | `echo $?` 输出 `exit=0` |
| 2 | **stdout 是 Markdown 报告** | 首行 `# 代码审查报告`，含 `- 评分：N/100` 与「发现一览」表格 |
| 3 | **命中工具已发现的 3 个问题** | 报告 findings 至少覆盖 L7 / L19 / L29（见 4.2） |
| 4 | **行号与文件名正确** | finding 的 `file` 为 `examples/bad_code.py`，`line` 落在真实缺陷行 |
| 5 | **运行记录落盘** | `.code_agent/runs/<run_id>.json` 存在，含 `messages / findings / trace / usage` |
| 6 | **无幻觉** | 报告里出现的文件必须真的被读过（抽查 `evidence` 片段与源文件一致） |

退出码语义：`0` 成功｜`1` 运行期错误（LLM/工具/无报告）｜`2` 配置或用法错误。

### 4.2 期望命中的缺陷（`examples/bad_code.py`）

**必中**——这 3 条 `run_lint` 工具会直接返回（B006/E722/UP031），属于"喂到嘴边"的证据：

| 行 | 缺陷 | ruff |
|---|---|---|
| L7 | `def load_config(path, cache={})` 可变默认参数 | B006 |
| L19 | `except:` 裸异常捕获 | E722 |
| L29 | `"SELECT ... '%s'" % name` SQL 注入 | UP031 |

**应中**——靠 `read_file` 阅读才能发现，检验 Agent 是否真在读代码：

| 行 | 缺陷 |
|---|---|
| L3 | `import json` 未使用 |
| L10 | `f = open(path)` 文件句柄未关闭（资源泄漏；与 `--focus "资源释放"` 直接相关） |
| L24 | `os.system("echo " + cmd)` 命令注入 |
| L36 | `for i in range(len(values))` 反模式 |

> `--focus` 只是提示词里的关注点，不是过滤条件；样本里**没有**并发问题，好的 Agent 应说明"未发现并发相关缺陷"，而不是硬编一条。

### 4.3 期望的元数据

- `评分` 0–100，与 findings 严重度大致自洽（有 critical 却给 95 分即为不自洽）。
- 每个 finding 有非空 `id / severity / category / file / title / detail`；有 `suggestion` 更佳。
- `- 审查文件：1 个`（单文件模式）。

---

## 5. 失败的大致归因

按"退出码 / 报错文案"定位。stderr 的 `msg=` 即为下表首列。

| 症状（stderr） | 退出码 | 大致归因 | 怎么确认 / 怎么办 |
|---|---|---|---|
| `配置错误：OPENAI_API_KEY is not set` | 2 | 未 export；或只写了 `.env` 但没启用方式 B | `echo $OPENAI_API_KEY`；确认是方式 A 还是 B |
| `LLM authentication failed` | 2 | key 无效/过期/被吊销；或 key 与端点不同源 | 检查 key 是否对应该 `OPENAI_BASE_URL` |
| `LLM request rejected (404)` | 1 | `CODE_AGENT_MODEL` 名在该端点不存在 | `-v` 看实际发出的 model；兼容端点要用它的模型名 |
| `LLM unavailable after retries` | 1 | 429 限流 / 网络不通 / 超时太短 | `-v` 里能看到 `retrying llm call attempt=N` 及次数；换网络或稍后重试 |
| `配置错误：path not found` 或 typer 用法报错 | 2 | 路径写错、参数非法（如 `--max-files 0`）、`-v` 与 `-q` 同用 | 看 usage 提示 |
| `未产出报告：agent degraded: max_iterations` | 1 | 模型全程不调工具、或迟迟不 `submit_review` | `-v` 看 `llm_response tool_calls=N`；N 长期为 0 说明模型不会用工具（工具能力弱的端点常见） |
| `未产出报告：agent degraded: invalid_report` | 1 | `submit_review` 参数不合 schema，修复重试 2 次仍失败 | `.code_agent/runs/*.json` 的 `trace` 里有 `repair` 事件，含失败原因 |
| `未产出报告：agent degraded: token_budget` | 1 | 上下文过大触发预算守卫 | 调大 `token_budget`（`AgentConfig`）或缩小 `--max-files` |
| 报告正常但 findings 为空 | 0 | 模型过于保守，或 `--focus` 太窄 | 对比 4.2 必中 3 条；空报告=不正常 |
| 有报告但行号对不上 / 出现未读过的文件 | 0 | 模型幻觉 | 抽查 `evidence`；属 prompt 层面问题，需加约束 |
| 报告里 `run_lint` 相关缺失 | 0 | 环境没装 ruff，工具返回 `ok:false` | `python -m ruff --version`；装了即恢复 |
| 进度卡住很久无输出 | — | 大仓库 + 大文件 + 多轮工具调用 | 加 `-v` 观察 `node=` / `tool=` 事件流，确认卡在哪一步 |

**通用排障三步**：
1. `python -m code_agent review <path> -v` → 看 stderr 的 `key=value` 事件流（`node_start / llm_response / tool_call / tool_result / repair`）。
2. 打开 `.code_agent/runs/<run_id>.json` → 看完整 `messages`（模型到底收到了什么）与 `trace`（哪一步失败）。
3. 二分定位：换 `--focus` 去掉、换单文件 vs 目录、换模型名——区分是 prompt、工具还是端点问题。

---

## 6. 结果记录模板

跑完把这张表填好贴回来，我按 §4 核对：

| 项 | 实测 |
|---|---|
| 命令 | `python -m code_agent review examples/bad_code.py --focus "并发与资源释放"` |
| 退出码 | |
| 评分 | |
| findings 条数 | |
| 命中 L7 / L19 / L29 | |
| 命中 L3 / L10 / L24 / L36 | |
| 行号是否准确 | |
| run journal 路径 | |
| 模型 / 端点 | |
| 耗时 / 大致 token | |
| 异常输出（若有） | |
