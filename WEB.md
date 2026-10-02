# WEB.md — 审查卷宗（本地 Web 界面）

> 一个用来**展示代码审查过程**的本地 Web 界面。
> 不只是看结论，而是看着 Agent 调工具、读代码、逐条落定。

---

## 1. 它是什么

CLI 的 `review` 命令跑完只给你一份报告；Web 端把**中间过程**也摊开：

- 左侧「过程」栏实时滚动：节点流转（`Collector → ReviewerAgent → Reporter`）、每次工具调用与耗时、修复重试。
- 右侧「发现」以卷宗形式逐条列出，严重度用颜色脊柱 + 序号呈现。
- 结束后可一键**复制 / 下载 Markdown**（与 CLI `--out` 同源内容）。

Web 端**不重复实现任何 Agent 逻辑**——它调用的是 CLI 用的同一个 `Workflow`。

---

## 2. 怎么启动

### 2.1 安装 Web 依赖（一次性）

Web 依赖是**可选 extra**，核心 CLI 不依赖它们：

```bash
cd D:/codeReviewAgent
pip install -e ".[web]"        # 只装 fastapi + uvicorn
```

若网络不稳，可加镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`

### 2.2 配置凭证

与 CLI 完全一致，只认环境变量：

```bash
export OPENAI_API_KEY=sk-你的key
# 走兼容端点时（如 DeepSeek）三者要配套：
export OPENAI_BASE_URL=https://api.deepseek.com/v1
export CODE_AGENT_MODEL=deepseek-chat
```

### 2.3 启动

```bash
python -m code_agent serve              # http://127.0.0.1:8000
python -m code_agent serve --port 8080  # 换端口
```

浏览器打开终端里打印的地址即可。`Ctrl-C` 停止。

> **只监听 127.0.0.1**。这不是一个能对外提供服务的东西，原因见 §5。

### 2.4 页面怎么用

1. 顶部「路径」填要审的文件或目录（默认 `examples/bad_code.py`）。
2. 可调 `Glob` / `上限` / `关注点`（关注点只是提示词里的侧重，不是过滤器）。
3. 点「开始审查」——左侧开始滚事件，右侧出结论。
4. 想留档就点「下载 .md」。

---

## 3. 设计说明

### 3.1 美学方向：工程卷宗

刻意避开"紫色渐变 + 圆角卡片"那套 SaaS 仪表盘。方向是**印在绘图纸上的工程卷宗**：

| 维度 | 选择 | 理由 |
|---|---|---|
| 底色 | 暖骨白 `#EDE9DF`，叠极淡横向栏线 + 纸纹颗粒 | 像稿纸/卷宗，不是屏幕 |
| 墨色 | 暖黑 `#171512`，非纯黑 | 印刷感，长时间看不刺眼 |
| 强调色 | **朱红 `#BC3618`**，全局仅此一点 | 单点强调胜过均匀铺色 |
| 严重度 | 同色系强度坡度（朱红→红橙→橄榄→灰绿），**并用左侧脊柱粗细编码** | 双通道编码，色弱也能分辨 |
| 标题 | `Bodoni Moda`（Didone 高对比衬线） | 印刷目录感，非默认无衬线 |
| 元数据 | `Azeret Mono`（宽字距大写字） | 仪器读数感，与代码同族 |
| 正文 | `Archivo` | 有性格的非 Inter 无衬线 |

字体通过 Google Fonts 渐进加载，**离线时有降级栈**（`Didot / Times New Roman`、`Cascadia Mono / Consolas`），不会崩成默认宋体。

### 3.2 布局

```
┌─ 报头（标题 + 模型/端点/凭证）────────────────────────────┐
├─ 委托（路径 / Glob / 上限 / 关注点 / 开始审查）───────────┤
├──────────────┬───────────────────────────────────────────┤
│ 读数（sticky）│  总述（大字号衬线总结 + 复制/下载）        │
│  评分 + 进度条 │                                           │
│  文件/发现/    │  发现                                       │
│  LLM/工具/Token│   01 ┃ 标题 · 严重度标签                    │
│  过程（实时流）│      文件:行 · 类别                        │
│               │      详情 / 建议 / 证据代码块               │
└──────────────┴───────────────────────────────────────────┘
```

刻意的非对称：左侧窄栏 19rem 作为"仪表"，右侧大留白承载卷宗正文；发现条目的序号是悬挂在左列的 Bodoni 大数字（`01`/`02`…），脊柱粗细随严重度变化。

### 3.3 动效

克制、只在三个高价值时刻出手：

1. **页面载入**：报头 → 委托 → 仪表 → 卷宗 依次错峰升起（`animation-delay` 60–220ms）。
2. **发现入场**：按 `--i` 递增延迟 70ms 逐条升起，形成"逐条落定"的节奏。
3. **实时事件**：每条 trace 从左侧滑入；评分数字用 `requestAnimationFrame` 缓动滚到目标值。

全部包在 `@media (prefers-reduced-motion: reduce)` 里，尊重系统设置。

---

## 4. 架构与数据流

```
浏览器
  │  POST /api/review  {path, glob, max_files, focus}
  ▼
FastAPI (src/code_agent/web/app.py)
  │  stream_review()  ← 复用同一个 Workflow(Collector, ReviewerAgent, Reporter)
  │  state.set_event_sink(queue.put_nowait)      ← 核心新增的订阅钩子
  ▼
WorkflowState.emit(TraceEvent)  ──►  asyncio.Queue  ──►  SSE 帧
  │                                                       │
  │  节点/工具/修复事件实时推给浏览器                        │
  ▼
执行结束 → {"type":"done", report, markdown, usage, warnings}
```

**帧协议**（`text/event-stream`，每帧 `data: {json}\n\n`）：

| type | 载荷 | 时机 |
|---|---|---|
| `start` | `run_id` | 立即 |
| `trace` | `event`（`TraceEvent`） | 每次 `state.emit` |
| `done` | `status / report / markdown / files / usage / warnings / error` | 流程结束 |
| `error` | `message` | 未捕获异常 |

**关键设计**：不新增任何"给 Web 用的"执行路径。给 `WorkflowState` 加了一个私有订阅钩子：

```python
state.set_event_sink(lambda event: queue.put_nowait(("trace", event)))
```

`emit()` 既写入 `state.trace`（CLI / 落盘照旧），也通知订阅者。这个钩子**不入序列化**，CLI 完全无感；同时也是项目2 多 Agent 编排做事件总线/可观测性的现成接口。

### 文件清单

| 文件 | 作用 |
|---|---|
| `src/code_agent/web/app.py` | FastAPI 应用：`/`、`/api/config`、`/api/review`(SSE)、静态托管 |
| `src/code_agent/web/static/index.html` | 页面结构（语义化标签） |
| `src/code_agent/web/static/styles.css` | 全部样式（CSS 变量 + 动效） |
| `src/code_agent/web/static/app.js` | SSE 解析、渲染、复制/下载 |
| `src/code_agent/cli.py` `serve()` | 启动命令，缺依赖时给明确提示 |

---

## 5. 安全边界（重要）

- 服务**默认只绑定 127.0.0.1**，无鉴权、无多用户隔离。
- 它**会读取你本机路径下的文件并把内容发给 LLM 端点**。这是它的用途，但也意味着：
  - **不要**用 `--host 0.0.0.0` 把它暴露到局域网/公网；
  - **不要**把路径指到含有密钥的目录（如 `~/.ssh`、`.env` 所在目录）。
- API key 只在**服务端**读取（`os.environ`），**永不下发到浏览器**；`/api/config` 只回 `has_key: bool` 和模型名，不回 key。
- 模型输出（标题/详情/证据）在 `app.js` 里一律走 `textContent` 写入，**从不使用 `innerHTML`**，避免报告内容注入页面。

---

## 6. 排障

| 现象 | 归因 | 处理 |
|---|---|---|
| 页面顶部提示「未检测到 OPENAI_API_KEY」 | 启动服务的终端没导出 key | `export` 后**重启** `serve`（环境变量在进程启动时读取） |
| 点「开始审查」后立刻报 400 | 同上，服务端缺凭证 | 看页面横幅提示 |
| 事件流停住，最后一条是 `LLM unavailable after retries` | 端点连不通/限流 | 确认 `OPENAI_BASE_URL`；`-v` 不适用时看服务端终端日志 |
| 报 404 / model not found | 模型名与端点不匹配 | 设 `CODE_AGENT_MODEL` 为该端点支持的模型 |
| 中文是方块/乱码 | 终端或字体 | 浏览器一般正常；终端里可 `chcp 65001` |
| 字体没生效（回退到衬线） | Google Fonts 被墙 | 设计有降级栈，可正常使用；想彻底离线可自行托管字体 |
| `serve` 报缺少 Web 依赖 | 未装 extra | `pip install -e ".[web]"` |

---

## 7. 与 CLI 的关系

| | CLI `review` | Web `/api/review` |
|---|---|---|
| 执行体 | `Workflow(Collector, Reviewer, Reporter)` | **同一个** |
| 报告来源 | `state.artifacts["markdown"]` | **同一个** |
| 事件 | 写 `state.trace` + stderr 日志 | 额外订阅推给浏览器 |
| 依赖 | 无额外依赖 | `[web]` extra |

两者是同一套 Agent 的两个观察窗口，不存在第二份业务逻辑。
