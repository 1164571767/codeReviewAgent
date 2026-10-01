# code-agent

代码审查 Agent（CLI）：给定代码路径，Agent 循环调用工具（读/搜/lint），LLM 产出结构化审查报告，CLI 渲染 Markdown。

设计见 [DESIGN.md](DESIGN.md)，执行计划见 [TASKS.md](TASKS.md)。

## 安装

```bash
pip install -e ".[dev]"
```

## 使用

```bash
python -m code_agent --help
```
