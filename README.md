# code-agent

代码审查 Agent（CLI）：给定代码路径，Agent 循环调用工具（读/搜/lint），LLM 产出结构化审查报告，CLI 渲染 Markdown。

设计见 [DESIGN.md](DESIGN.md)，执行计划见 [TASKS.md](TASKS.md)。

## 安装

```bash
pip install -e ".[dev]"
```

## 使用

```bash
export OPENAI_API_KEY=sk-...
# 可选：指向 OpenAI 兼容端点（DeepSeek 等）
export OPENAI_BASE_URL=https://api.deepseek.com/v1
export CODE_AGENT_MODEL=deepseek-chat

python -m code_agent review examples/bad_code.py --focus "并发与资源释放"
python -m code_agent review src/ --glob "**/*.py" --max-files 10 --out report.md
```

退出码：`0` 成功，`1` 运行期错误，`2` 配置/用法错误。
