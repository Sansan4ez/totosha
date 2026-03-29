function ensureTrailingSlashForDirectory() {
  const p = window.location.pathname || "/";
  const last = p.split("/").filter(Boolean).slice(-1)[0] || "";
  const hasExt = last.includes(".");
  if (p.endsWith("/") || hasExt) return;
  const next = `${window.location.origin}${p}/${window.location.search || ""}${window.location.hash || ""}`;
  window.location.replace(next);
}

ensureTrailingSlashForDirectory();

function benchPrefixFromPathname() {
  const p = window.location.pathname || "";
  const m = p.match(/^(.*)\/bench\/dashboard(?:\/|$)/);
  if (!m) return null;
  const prefix = m[1] || "";
  return `${prefix}/bench`;
}

function indexUrlCandidates() {
  const rel = "../reports/index.json";
  const c = [rel];
  const benchPrefix = benchPrefixFromPathname();
  if (benchPrefix) c.push(`${benchPrefix}/reports/index.json`);
  // If server root is `bench/` and URL is `/dashboard/`, rel already works.
  return Array.from(new Set(c));
}

function latestUrlCandidates() {
  const rel = "../reports/latest.json";
  const c = [rel];
  const benchPrefix = benchPrefixFromPathname();
  if (benchPrefix) c.push(`${benchPrefix}/reports/latest.json`);
  return Array.from(new Set(c));
}

const el = (id) => document.getElementById(id);

const state = {
  index: null,
  report: null,
  charts: {
    outcome: null,
    latency: null,
    tags: null,
  },
};

function showError(message, err) {
  const box = el("errors");
  const body = el("errorsBody");
  if (!box || !body) return;
  const lines = [];
  if (message) lines.push(String(message));
  if (err) {
    if (err instanceof Error) {
      lines.push(`${err.name}: ${err.message}`);
      if (err.stack) lines.push(err.stack);
    } else {
      lines.push(String(err));
    }
  }
  body.textContent = lines.join("\n");
  box.hidden = false;
}

window.addEventListener("error", (ev) => {
  try {
    showError("Uncaught error", ev?.error || ev?.message || "");
  } catch (_) {}
});

window.addEventListener("unhandledrejection", (ev) => {
  try {
    showError("Unhandled promise rejection", ev?.reason || "");
  } catch (_) {}
});

function fmtPct(x) {
  if (typeof x !== "number" || !isFinite(x)) return "-";
  return `${(x * 100).toFixed(2)}%`;
}

function fmtNum(x) {
  if (typeof x !== "number" || !isFinite(x)) return "-";
  return x.toLocaleString("en-US");
}

function fmtMs(x) {
  if (typeof x !== "number" || !isFinite(x)) return "-";
  if (x >= 1000) return `${(x / 1000).toFixed(2)}s`;
  return `${x.toFixed(0)}ms`;
}

function fmtUSD(x) {
  if (typeof x !== "number" || !isFinite(x)) return "-";
  return `$${x.toFixed(3)}`;
}

function resolveBenchPath(p) {
  if (!p) return null;
  const s = String(p);
  if (s.startsWith("bench/")) return `../${s.slice("bench/".length)}`;
  if (s.startsWith("./bench/")) return `../${s.slice("./bench/".length)}`;
  return s;
}

function setText(target, value) {
  const node = typeof target === "string" ? el(target) : target;
  if (!node) return;
  node.textContent = value == null ? "" : String(value);
}

async function fetchJson(url) {
  const bust = url.includes("?") ? `&t=${Date.now()}` : `?t=${Date.now()}`;
  const res = await fetch(`${url}${bust}`, { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status} ${url}: ${text.slice(0, 200)}`);
  }
  return await res.json();
}

async function fetchFirstJson(candidates) {
  let lastErr = null;
  for (const url of candidates) {
    try {
      return await fetchJson(url);
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error("no candidates");
}

function showFallback(on) {
  el("fallback").hidden = !on;
}

function setRunSelectEnabled(enabled) {
  el("runSelect").disabled = !enabled;
}

function buildRunLabel(run) {
  const rid = run.run_id || "-";
  const ts = run.started_at ? run.started_at.replace("T", " ").replace("Z", "") : "";
  const pr = typeof run.pass_rate === "number" ? `pass=${fmtPct(run.pass_rate)}` : "pass=-";
  const miss = typeof run.missing_results === "number" ? `missing=${run.missing_results}` : "";
  return `${rid}  •  ${pr}${miss ? `  •  ${miss}` : ""}${ts ? `  •  ${ts}` : ""}`;
}

function populateRunSelect(index) {
  const select = el("runSelect");
  select.innerHTML = "";
  const runs = Array.isArray(index?.runs) ? index.runs : [];
  for (const run of runs) {
    const opt = document.createElement("option");
    opt.value = resolveBenchPath(run.report_path || "");
    opt.textContent = buildRunLabel(run);
    opt.dataset.runId = run.run_id || "";
    select.appendChild(opt);
  }
  setRunSelectEnabled(runs.length > 0);
}

function getSummary(report) {
  const s = report?.summary;
  return s && typeof s === "object" ? s : {};
}

function getCases(report) {
  const cases = report?.cases;
  return Array.isArray(cases) ? cases : [];
}

function getCaseStatus(c) {
  if (c?.scoring?.missing) return "missing_result";
  return c?.result?.status || "unknown";
}

function getCasePassed(c) {
  return Boolean(c?.scoring?.passed);
}

function getCaseDurationMs(c) {
  const v = c?.result?.duration_ms;
  return typeof v === "number" ? v : typeof v === "string" ? Number(v) : null;
}

function getCaseTokensTotal(c) {
  const usage = c?.result?.meta?.llm_usage;
  const v = usage?.total_tokens;
  return typeof v === "number" ? v : null;
}

function getCaseCost(c) {
  const v = c?.result?.estimated_cost_usd;
  return typeof v === "number" ? v : null;
}

function renderKpis(report) {
  const s = getSummary(report);

  setText("kpiPassRate", fmtPct(s.pass_rate));
  setText("kpiCounts", `${fmtNum(s.pass)} / ${fmtNum(s.fail)} / ${fmtNum(s.missing_results)}`);
  setText("kpiLatency", `${fmtMs(s.duration_ms_p50)} / ${fmtMs(s.duration_ms_p95)}`);
  setText("kpiTokens", fmtNum(s.tokens_total));
  setText("kpiCost", s.estimated_cost_usd_total == null ? "-" : fmtUSD(s.estimated_cost_usd_total));
  setText("kpiRunId", s.run_id || "-");
}

function initCharts() {
  const outcomeEl = el("chartOutcome");
  const latencyEl = el("chartLatency");
  const tagsEl = el("chartTags");

  try {
    if (typeof echarts === "undefined") throw new Error("ECharts not loaded (script failed to load)");
    state.charts.outcome = echarts.init(outcomeEl);
    state.charts.latency = echarts.init(latencyEl);
    state.charts.tags = echarts.init(tagsEl);
  } catch (e) {
    showError("Charts disabled", e);
    state.charts.outcome = null;
    state.charts.latency = null;
    state.charts.tags = null;
  }

  window.addEventListener("resize", () => {
    state.charts.outcome?.resize();
    state.charts.latency?.resize();
    state.charts.tags?.resize();
  });
}

function renderOutcomeChart(report) {
  if (!state.charts.outcome) return;
  const s = getSummary(report);
  const pass = Number(s.pass || 0);
  const fail = Number(s.fail || 0);
  const missing = Number(s.missing_results || 0);

  const opt = {
    backgroundColor: "transparent",
    tooltip: { trigger: "item" },
    legend: {
      bottom: 0,
      textStyle: { color: "rgba(255,255,255,0.75)" },
    },
    series: [
      {
        type: "pie",
        radius: ["46%", "74%"],
        avoidLabelOverlap: true,
        label: { color: "rgba(255,255,255,0.85)" },
        labelLine: { lineStyle: { color: "rgba(255,255,255,0.35)" } },
        data: [
          { value: pass, name: "pass", itemStyle: { color: "#6ee7a8" } },
          { value: fail, name: "fail", itemStyle: { color: "#ff6b6b" } },
          { value: missing, name: "missing", itemStyle: { color: "#ffd166" } },
        ],
      },
    ],
  };

  try {
    state.charts.outcome.setOption(opt, true);
  } catch (e) {
    showError("Outcome chart error", e);
  }
}

function renderLatencyChart(report) {
  if (!state.charts.latency) return;
  const cases = getCases(report)
    .map((c) => {
      const dur = getCaseDurationMs(c);
      return { c, dur: typeof dur === "number" && isFinite(dur) ? dur : null };
    })
    .filter((x) => x.dur != null);

  cases.sort((a, b) => b.dur - a.dur);

  const x = cases.map((x) => x.c.case_id);
  const y = cases.map((x) => x.dur);
  const colors = cases.map((x) => {
    if (x.c.scoring?.missing) return "#ffd166";
    const status = getCaseStatus(x.c);
    if (status !== "ok") return "#ffd166";
    return getCasePassed(x.c) ? "#6ee7a8" : "#ff6b6b";
  });

  const opt = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (items) => {
        const item = Array.isArray(items) ? items[0] : items;
        const i = item.dataIndex;
        const c = cases[i]?.c;
        const status = getCaseStatus(c);
        const passed = getCasePassed(c);
        return [
          `<div style="font-family: ui-monospace, monospace">${c.case_id}</div>`,
          `duration: <b>${fmtMs(y[i])}</b>`,
          `status: <b>${status}</b>`,
          `passed: <b>${passed}</b>`,
        ].join("<br/>");
      },
    },
    grid: { left: 24, right: 14, top: 8, bottom: 42, containLabel: true },
    xAxis: {
      type: "category",
      data: x,
      axisLabel: { color: "rgba(255,255,255,0.65)", rotate: 35, fontFamily: "IBM Plex Mono" },
      axisLine: { lineStyle: { color: "rgba(255,255,255,0.15)" } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: "rgba(255,255,255,0.65)" },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.10)" } },
    },
    series: [
      {
        type: "bar",
        data: y.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
        barMaxWidth: 22,
      },
    ],
  };

  try {
    state.charts.latency.setOption(opt, true);
  } catch (e) {
    showError("Latency chart error", e);
  }
}

function renderTagsChart(report) {
  if (!state.charts.tags) return;
  const s = getSummary(report);
  const tagsObj = s.tags && typeof s.tags === "object" ? s.tags : {};
  const rows = Object.entries(tagsObj).map(([tag, v]) => {
    const passRate = typeof v?.pass_rate === "number" ? v.pass_rate : 0;
    const pass = typeof v?.pass === "number" ? v.pass : 0;
    const total = typeof v?.total === "number" ? v.total : 0;
    return { tag, passRate, pass, total };
  });
  rows.sort((a, b) => b.passRate - a.passRate);

  const x = rows.map((r) => r.tag);
  const y = rows.map((r) => r.passRate);

  const opt = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (items) => {
        const item = items?.[0];
        if (!item) return "";
        const r = rows[item.dataIndex];
        return `${r.tag}<br/>pass_rate: <b>${fmtPct(r.passRate)}</b><br/>pass/total: <b>${r.pass}/${r.total}</b>`;
      },
    },
    grid: { left: 24, right: 14, top: 8, bottom: 36, containLabel: true },
    xAxis: {
      type: "category",
      data: x,
      axisLabel: { color: "rgba(255,255,255,0.65)", fontFamily: "IBM Plex Mono" },
      axisLine: { lineStyle: { color: "rgba(255,255,255,0.15)" } },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 1,
      axisLabel: { color: "rgba(255,255,255,0.65)", formatter: (v) => `${Math.round(v * 100)}%` },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.10)" } },
    },
    series: [
      {
        type: "bar",
        data: y,
        barMaxWidth: 26,
        itemStyle: { color: "#6ee7ff" },
      },
    ],
  };

  try {
    state.charts.tags.setOption(opt, true);
  } catch (e) {
    showError("Tags chart error", e);
  }
}

function renderCharts(report) {
  renderOutcomeChart(report);
  renderLatencyChart(report);
  renderTagsChart(report);
}

function buildBadge({ kind, text }) {
  const span = document.createElement("span");
  span.className = "badge";

  const dot = document.createElement("span");
  dot.className = "dot";
  if (kind === "good") dot.classList.add("dotGood");
  if (kind === "bad") dot.classList.add("dotBad");
  if (kind === "warn") dot.classList.add("dotWarn");
  span.appendChild(dot);

  const label = document.createElement("span");
  label.textContent = text;
  span.appendChild(label);

  return span;
}

function renderTable(report) {
  const body = el("casesBody");
  body.innerHTML = "";

  const query = (el("caseSearch").value || "").trim().toLowerCase();
  const filter = el("caseFilter").value || "all";

  const cases = getCases(report).filter((c) => {
    const status = getCaseStatus(c);
    const passed = getCasePassed(c);
    const missing = Boolean(c?.scoring?.missing);
    const nonOk = status !== "ok" && !missing;
    const failed = !missing && status === "ok" && !passed;

    if (filter === "passed" && !passed) return false;
    if (filter === "failed" && !failed) return false;
    if (filter === "missing" && !missing) return false;
    if (filter === "non_ok" && !nonOk) return false;

    if (!query) return true;
    const hay = [
      c.case_id,
      Array.isArray(c.tags) ? c.tags.join(" ") : "",
      c.question,
      c?.result?.answer || "",
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(query);
  });

  for (const c of cases) {
    const tr = document.createElement("tr");
    tr.className = "caseRow";
    tr.addEventListener("click", () => renderDetail(c));

    const tdId = document.createElement("td");
    tdId.className = "caseIdCell";
    tdId.textContent = c.case_id || "-";
    tr.appendChild(tdId);

    const tdTags = document.createElement("td");
    tdTags.textContent = Array.isArray(c.tags) ? c.tags.join(", ") : "-";
    tr.appendChild(tdTags);

    const status = getCaseStatus(c);
    const tdStatus = document.createElement("td");
    tdStatus.textContent = status;
    tr.appendChild(tdStatus);

    const tdScore = document.createElement("td");
    if (c?.scoring?.missing) {
      tdScore.appendChild(buildBadge({ kind: "warn", text: "MISSING" }));
    } else if (status !== "ok") {
      tdScore.appendChild(buildBadge({ kind: "warn", text: "NON_OK" }));
    } else if (getCasePassed(c)) {
      tdScore.appendChild(buildBadge({ kind: "good", text: "PASS" }));
    } else {
      tdScore.appendChild(buildBadge({ kind: "bad", text: "FAIL" }));
    }
    tr.appendChild(tdScore);

    const tdDur = document.createElement("td");
    tdDur.className = "num";
    const dur = getCaseDurationMs(c);
    tdDur.textContent = typeof dur === "number" ? dur.toFixed(1) : "-";
    tr.appendChild(tdDur);

    const tdTok = document.createElement("td");
    tdTok.className = "num";
    const tok = getCaseTokensTotal(c);
    tdTok.textContent = typeof tok === "number" ? String(tok) : "-";
    tr.appendChild(tdTok);

    const tdCost = document.createElement("td");
    tdCost.className = "num";
    const cost = getCaseCost(c);
    tdCost.textContent = typeof cost === "number" ? cost.toFixed(3) : "-";
    tr.appendChild(tdCost);

    body.appendChild(tr);
  }
}

function renderDetail(c) {
  const root = el("detailBody");
  root.innerHTML = "";

  const title = document.createElement("div");
  title.className = "detailMetaTitle";
  title.textContent = `${c.case_id || "-"}   [${Array.isArray(c.tags) ? c.tags.join(", ") : "-"}]`;
  root.appendChild(title);

  const status = getCaseStatus(c);
  const passed = getCasePassed(c);
  const errors = Array.isArray(c?.scoring?.errors) ? c.scoring.errors : [];
  const reqId = c?.result?.request_id || "";

  const meta = c?.result?.meta || null;
  const tools = Array.isArray(meta?.tools_used) ? meta.tools_used : [];
  const llmCalls = typeof meta?.llm_calls === "number" ? meta.llm_calls : null;
  const llmTime = typeof meta?.llm_time_ms === "number" ? meta.llm_time_ms : null;
  const usage = meta?.llm_usage || null;

  const kv = (k, v) => {
    const row = document.createElement("div");
    row.className = "kv";
    const kk = document.createElement("div");
    kk.className = "kvKey";
    kk.textContent = k;
    const vv = document.createElement("div");
    vv.className = "kvVal";
    vv.textContent = v;
    row.appendChild(kk);
    row.appendChild(vv);
    return row;
  };

  root.appendChild(kv("status", status));
  root.appendChild(kv("passed", String(passed)));
  if (reqId) root.appendChild(kv("request_id", reqId));
  const dur = getCaseDurationMs(c);
  if (typeof dur === "number") root.appendChild(kv("duration_ms", dur.toFixed(3)));
  const cost = getCaseCost(c);
  if (typeof cost === "number") root.appendChild(kv("estimated_cost_usd", cost.toFixed(6)));
  const tok = getCaseTokensTotal(c);
  if (typeof tok === "number") root.appendChild(kv("tokens_total", String(tok)));
  if (llmCalls != null) root.appendChild(kv("llm_calls", String(llmCalls)));
  if (llmTime != null) root.appendChild(kv("llm_time_ms", llmTime.toFixed(1)));
  if (tools.length) root.appendChild(kv("tools_used", tools.join(", ")));
  if (usage && typeof usage === "object") root.appendChild(kv("llm_usage", JSON.stringify(usage)));
  if (errors.length) root.appendChild(kv("errors", errors.join(" | ")));

  const section = (label, text) => {
    const wrap = document.createElement("div");
    wrap.className = "detailSection";
    const h = document.createElement("div");
    h.className = "detailSectionTitle";
    h.textContent = label;
    const pre = document.createElement("div");
    pre.className = "detailSectionText";
    pre.textContent = text || "";
    wrap.appendChild(h);
    wrap.appendChild(pre);
    return wrap;
  };

  root.appendChild(section("Question", c.question || ""));
  root.appendChild(section("Answer", c?.result?.answer || ""));
  root.appendChild(section("Golden answer", c?.golden?.answer || ""));
  if (Array.isArray(c?.golden?.evidence) && c.golden.evidence.length) {
    root.appendChild(section("Evidence", JSON.stringify(c.golden.evidence, null, 2)));
  }
  if (Array.isArray(c?.golden?.checks) && c.golden.checks.length) {
    root.appendChild(section("Checks", JSON.stringify(c.golden.checks, null, 2)));
  }
}

function renderAll(report) {
  state.report = report;
  try {
    renderKpis(report);
  } catch (e) {
    showError("KPI render error", e);
  }
  try {
    renderCharts(report);
  } catch (e) {
    showError("Charts render error", e);
  }
  try {
    renderTable(report);
  } catch (e) {
    showError("Table render error", e);
  }
}

async function loadIndex() {
  showFallback(false);
  setRunSelectEnabled(false);

  const tried = indexUrlCandidates();
  let idx;
  try {
    idx = await fetchFirstJson(tried);
  } catch (e) {
    console.warn("Failed to load index:", e);
    const dbg = el("fallbackDebug");
    if (dbg) dbg.textContent = `Tried: ${tried.join(" , ")}  |  location: ${window.location.pathname}`;
    showFallback(true);
    showError("Failed to fetch index.json", e);
    return;
  }

  state.index = idx;
  try {
    populateRunSelect(idx);
  } catch (e) {
    showError("Failed to populate run selector", e);
  }

  try {
    const runs = Array.isArray(idx?.runs) ? idx.runs : [];
    if (runs.length) {
      const first = runs[0];
      const url = resolveBenchPath(first.report_path);
      if (url) await loadReport(url);
    }
  } catch (e) {
    showError("Failed to load/render the first run report", e);
  }
}

async function loadReport(url) {
  if (!url) return;
  const report = await fetchJson(url);
  renderAll(report);
}

async function loadLatest() {
  try {
    const report = await fetchFirstJson(latestUrlCandidates());
    renderAll(report);
  } catch (e) {
    console.warn("Failed to load latest:", e);
  }
}

function bindUi() {
  el("reloadBtn").addEventListener("click", () => loadIndex());
  el("latestBtn").addEventListener("click", () => loadLatest());

  el("runSelect").addEventListener("change", async (ev) => {
    const url = ev.target.value;
    try {
      await loadReport(url);
    } catch (e) {
      console.warn("Failed to load report:", e);
    }
  });

  el("caseSearch").addEventListener("input", () => renderTable(state.report));
  el("caseFilter").addEventListener("change", () => renderTable(state.report));

  el("reportFile").addEventListener("change", async (ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const obj = JSON.parse(text);
      showFallback(false);
      renderAll(obj);
    } catch (e) {
      console.warn("Failed to load report file:", e);
    }
  });
}

function boot() {
  bindUi();
  initCharts();
  loadIndex();
}

boot();
