/* 审查卷宗 — front-end logic.
   All dynamic text goes through textContent (never innerHTML): model output
   is untrusted and must not be able to inject markup. */

"use strict";

const $ = (id) => document.getElementById(id);

const SEVERITY_LABEL = {
  critical: "严重",
  high: "高危",
  medium: "中等",
  low: "轻微",
  info: "提示",
};

const EVENT_LABEL = {
  node_start: "进入",
  node_end: "结束",
  llm_response: "模型回复",
  tool_call: "调用",
  tool_result: "返回",
  repair: "修复重试",
};

let lastMarkdown = "";
let running = false;

/* ------------------------------------------------------------- dom helper */

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "style") node.setAttribute("style", value);
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child) node.append(child);
  }
  return node;
}

function two(n) {
  return String(n).padStart(2, "0");
}

function clock(date = new Date()) {
  return `${two(date.getHours())}:${two(date.getMinutes())}:${two(date.getSeconds())}`;
}

/* ------------------------------------------------------------------ banner */

function setBanner(message, tone = "error") {
  const banner = $("banner");
  if (!message) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }
  banner.hidden = false;
  banner.dataset.tone = tone;
  banner.textContent = message;
}

/* ------------------------------------------------------------------ config */

async function loadConfig() {
  try {
    const response = await fetch("/api/config");
    const config = await response.json();
    $("meta-model").textContent = config.model;
    try {
      $("meta-endpoint").textContent = new URL(config.base_url).host;
    } catch {
      $("meta-endpoint").textContent = config.base_url;
    }
    const key = $("meta-key");
    key.textContent = config.has_key ? "已就绪" : "缺失";
    key.dataset.tone = config.has_key ? "ok" : "bad";
    if (!config.has_key) {
      setBanner(
        "未检测到 OPENAI_API_KEY。请在启动服务的终端里 export 后重启服务。",
        "warn"
      );
    }
  } catch (error) {
    setBanner(`无法读取服务配置：${error}`);
  }
}

/* ------------------------------------------------------------------- trace */

function appendTrace(event) {
  const list = $("trace");
  const kind =
    event.event === "tool_call" ? "tool"
    : event.event === "tool_result" ? (event.ok ? "ok" : "fail")
    : event.event === "repair" ? "fail"
    : "meta";

  const label = EVENT_LABEL[event.event] || event.event;
  const tool = event.data && event.data.tool ? ` ${event.data.tool}` : "";
  const dur =
    event.dur_ms === null || event.dur_ms === undefined ? "" : ` ${event.dur_ms}ms`;

  const body = el("span", { class: "trace__body" }, [
    el("span", { class: "trace__ev", text: `${label}${tool}` }),
  ]);
  if (dur) body.append(el("span", { class: "trace__dur", text: dur }));

  const row = el("li", { class: "trace__row", "data-kind": kind }, [
    el("span", { class: "trace__time", text: clock() }),
    body,
  ]);

  list.append(row);
  list.scrollTop = list.scrollHeight;
}

function resetView() {
  $("trace").replaceChildren();
  $("findings-list").replaceChildren();
  $("notes-list").replaceChildren();
  $("idle").hidden = true;
  $("summary").hidden = true;
  $("findings").hidden = true;
  $("notes").hidden = true;
  $("score").textContent = "—";
  $("score-fill").style.width = "0%";
  for (const id of ["stat-files", "stat-findings", "stat-llm", "stat-tools", "stat-tokens"]) {
    $(id).textContent = "0";
  }
  setBanner("");
  setTraceState("running");
}

function setTraceState(state) {
  const badge = $("trace-state");
  badge.dataset.state = state;
  badge.textContent = { idle: "待机", running: "运行中", done: "完成", failed: "失败" }[state];
}

/* ---------------------------------------------------------------- score */

function bandFor(score) {
  if (score >= 80) return "ok";
  if (score >= 60) return "mid";
  if (score >= 40) return "warn";
  return "bad";
}

function countUp(node, target, duration = 750) {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    node.textContent = String(target);
    return;
  }
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    node.textContent = String(Math.round(target * eased));
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/* ---------------------------------------------------------------- findings */

function renderFinding(finding, index) {
  const severity = finding.severity || "info";
  const location = finding.line ? `${finding.file}:${finding.line}` : finding.file;

  const head = el("div", { class: "finding__body" }, [
    el("h3", { class: "finding__title", text: finding.title }),
    el("p", { class: "finding__loc", text: `${location} · ${finding.category}` }),
    el("p", { class: "finding__detail", text: finding.detail }),
  ]);

  if (finding.suggestion) head.append(el("p", { class: "finding__fix", text: finding.suggestion }));
  if (finding.evidence) {
    head.append(el("pre", { class: "finding__evidence", text: finding.evidence }));
  }

  return el(
    "li",
    {
      class: `finding finding--${severity}`,
      style: `--i:${index}`,
    },
    [
      el("div", {}, [
        el("span", { class: "finding__no", text: String(index + 1).padStart(2, "0") }),
        el("span", { class: "finding__sev", text: SEVERITY_LABEL[severity] || severity }),
      ]),
      head,
    ]
  );
}

function renderReport(frame) {
  const report = frame.report;
  const usage = frame.usage || {};

  $("stat-files").textContent = String((frame.files || []).length);
  $("stat-findings").textContent = String(report ? report.findings.length : 0);
  $("stat-llm").textContent = String(usage.llm_calls ?? 0);
  $("stat-tools").textContent = String(usage.tool_calls ?? 0);
  $("stat-tokens").textContent = String(
    (usage.prompt_tokens ?? 0) + (usage.completion_tokens ?? 0)
  );

  const score = report ? report.score : 0;
  const band = bandFor(score);
  $("score-fill").dataset.band = band;
  $("score-fill").style.width = `${score}%`;
  countUp($("score"), score);

  if (report) {
    $("summary").hidden = false;
    $("summary-text").textContent = report.summary;
    lastMarkdown = frame.markdown || "";

    const list = $("findings-list");
    list.replaceChildren();
    report.findings.forEach((finding, index) => list.append(renderFinding(finding, index)));
    $("findings").hidden = report.findings.length === 0;
    $("findings-count").textContent = report.findings.length
      ? `${report.findings.length} 条 · 按严重度排序`
      : "";
  }

  if (frame.warnings && frame.warnings.length) {
    const list = $("notes-list");
    list.replaceChildren();
    for (const warning of frame.warnings) list.append(el("li", { text: warning }));
    $("notes").hidden = false;
  }

  if (frame.status === "failed") {
    setTraceState("failed");
    setBanner(frame.error || "本次审查未产出报告。");
  } else {
    setTraceState("done");
  }
}

/* -------------------------------------------------------------------- run */

function setRunning(state) {
  running = state;
  const button = $("run");
  button.disabled = state;
  button.querySelector(".run__label").textContent = state ? "审查中…" : "开始审查";
}

async function run(event) {
  event.preventDefault();
  if (running) return;

  const payload = {
    path: $("path").value.trim(),
    glob: $("glob").value.trim() || "**/*.py",
    max_files: Number($("max-files").value) || 20,
    focus: $("focus").value.trim() || null,
  };
  if (!payload.path) {
    setBanner("请填写要审查的路径。", "warn");
    return;
  }

  resetView();
  setRunning(true);
  try {
    const response = await fetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      setTraceState("failed");
      setBanner(detail.detail || `请求失败：${response.status}`);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const line = frame.split("\n").find((l) => l.startsWith("data: "));
        if (line) handleFrame(JSON.parse(line.slice(6)));
        boundary = buffer.indexOf("\n\n");
      }
    }
  } catch (error) {
    setTraceState("failed");
    setBanner(`连接中断：${error}`);
  } finally {
    setRunning(false);
  }
}

function handleFrame(frame) {
  if (frame.type === "trace") appendTrace(frame.event);
  else if (frame.type === "done") renderReport(frame);
  else if (frame.type === "error") {
    setTraceState("failed");
    setBanner(frame.message);
  }
}

/* --------------------------------------------------------------- markdown */

async function copyMarkdown() {
  if (!lastMarkdown) return;
  try {
    await navigator.clipboard.writeText(lastMarkdown);
    setBanner("");
    flash($("copy-md"), "已复制");
  } catch {
    setBanner("剪贴板不可用，请改用「下载 .md」。", "warn");
  }
}

function downloadMarkdown() {
  if (!lastMarkdown) return;
  const blob = new Blob([lastMarkdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = el("a", { href: url, download: "review-report.md" });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function flash(button, text) {
  const original = button.textContent;
  button.textContent = text;
  setTimeout(() => {
    button.textContent = original;
  }, 1200);
}

/* ------------------------------------------------------------------ start */

$("form").addEventListener("submit", run);
$("copy-md").addEventListener("click", copyMarkdown);
$("download-md").addEventListener("click", downloadMarkdown);
loadConfig();
