const GRADE_ZH = {
  High: "高", Moderate: "中", Low: "低", "Very low": "极低", "N/A": "未分级",
};
const GRADE_COLOR = {
  High: "#038F49", Moderate: "#4B97B8", Low: "#F5E400",
  "Very low": "#F03A2C", "N/A": "#A7A7A7",
};

// 根据背景亮度自动选深/浅文字，避免亮黄底配白字看不清
function contrastText(hex) {
  const m = String(hex || "").replace("#", "");
  if (m.length < 6) return "#fff";
  const r = parseInt(m.substr(0, 2), 16);
  const g = parseInt(m.substr(2, 2), 16);
  const b = parseInt(m.substr(4, 2), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.6 ? "#1f2430" : "#fff";
}
const STYPE_ZH = {
  meta_analysis: "Meta 分析",
  systematic_review: "系统综述",
  guideline: "指南 / 共识",
  randomized_controlled_trial: "随机对照试验",
  clinical_trial: "临床试验",
  cohort: "队列研究",
  case_control: "病例对照",
  case_report: "病例报告",
  review: "综述",
  basic: "基础研究",
  other: "其他",
};
const GRADE_ORDER = ["High", "Moderate", "Low", "Very low", "N/A"];

const $ = (id) => document.getElementById(id);

function setStatus(online) {
  const s = $("status");
  s.classList.remove("online", "offline");
  if (online === null) {
    $("statusText").textContent = "连接中…";
  } else if (online) {
    s.classList.add("online");
    $("statusText").textContent = "PubMed 在线";
  } else {
    s.classList.add("offline");
    $("statusText").textContent = "离线模式";
  }
}

async function checkHealth() {
  try {
    const r = await fetch("/health");
    const d = await r.json();
    setStatus(!!d.pubmed_online);
    renderHomeStatus(d);
  } catch {
    setStatus(false);
    renderHomeStatus(null);
  }
}

function esc(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[c]));
}

const POLARITY = {
  support: { label: "支持", mark: "✓", color: "#16a34a" },
  against: { label: "反对", mark: "✗", color: "#ef4444" },
  neutral: { label: "中立", mark: "·", color: "#94a3b8" },
};

function renderAnswer(data) {
  const body = $("answerBody");
  body.innerHTML = "";
  if (data.sentences && data.sentences.length) {
    data.sentences.forEach((s) => {
      const p = document.createElement("p");
      p.className = "answer-sentence";
      const pol = POLARITY[s.polarity] || POLARITY.neutral;
      const mark = document.createElement("span");
      mark.className = "pol-mark";
      mark.style.color = pol.color;
      mark.title = "结论方向：" + pol.label;
      mark.textContent = pol.mark + " ";
      p.appendChild(mark);
      p.appendChild(document.createTextNode(s.sentence + " "));
      const cite = document.createElement("span");
      cite.className = "cite";
      cite.textContent = `[PMID ${s.pmid}]`;
      p.appendChild(cite);
      body.appendChild(p);
    });
  } else {
    const p = document.createElement("p");
    p.textContent = data.answer || "未能生成回答，请换一种问法。";
    body.appendChild(p);
  }
  $("modeBadge").textContent =
    data.mode === "llm" ? "生成式回答（LLM）" : "抽取式回答（离线）";
}

function renderStats(data, elapsedMs, ev) {
  // 判定状态：support / against / conflict / neutral
  let state = "neutral";
  if (ev) {
    if (ev.conflict) state = "conflict";
    else if (ev.verdict === "证据倾向支持") state = "support";
    else if (ev.verdict === "证据倾向不支持") state = "against";
  }

  // 卡 1：证据置信度
  $("confidenceNum").textContent = ev ? ev.confidence : "–";

  // 卡 2：证据判定
  $("verdictText").textContent = ev ? ev.verdict : "–";
  const statCards = document.querySelectorAll("#result .stat-card");
  const verdictCard = statCards[1];
  verdictCard.classList.remove("verdict-support", "verdict-against", "verdict-conflict");
  if (state !== "neutral") verdictCard.classList.add("verdict-" + state);
  $("verdictSub").textContent = ev && ev.conflict ? "文献结论存在对立，采信需谨慎" : "";
  $("polarityLine").textContent = ev
    ? `支持 ${ev.support_count} · 反对 ${ev.against_count} · 中立 ${ev.neutral_count}`
    : "";

  // 卡 3：文献命中
  $("hitNum").textContent = data.total.toLocaleString();
  $("hitSub").textContent = `返回 ${data.results.length} 篇 · ${data.online ? "PubMed 在线" : "离线语料"}`;

  // 卡 4：响应耗时
  const sec = elapsedMs / 1000;
  $("timeNum").textContent = sec >= 1 ? sec.toFixed(1) + "s" : Math.round(elapsedMs) + "ms";
  $("timeSub").textContent = data.mode === "llm" ? "生成式回答" : "抽取式回答";

  $("resultMeta").textContent = `「${data.query}」`;

  // 完整性告警（撤稿 / 存疑 / 更正）
  const warn = $("integrityWarning");
  if (ev && ev.integrity_warning) {
    warn.textContent = "注意：" + ev.integrity_warning;
    warn.classList.remove("hidden");
  } else {
    warn.classList.add("hidden");
  }

  renderConfidence(ev ? ev.confidence : 0);
}

/* ---------- 首页仪表盘 ---------- */
const ASKCOUNT_KEY = "medlit.askCount";

function getAskCount() {
  return Number(localStorage.getItem(ASKCOUNT_KEY) || 0);
}

/* 由 /health 数据填充首页四张状态卡 */
function renderHomeStatus(h) {
  const online = !!(h && h.pubmed_online);
  const svc = $("homeSvc");
  svc.textContent = online ? "在线" : "离线";
  svc.style.color = online ? "#038f4a" : "#b45309";
  $("homeSvcSub").textContent = online
    ? "PubMed E-utilities 实时检索已连通"
    : "联网失败 · 自动回退内置示例语料";

  const loaded = !!(h && h.model_loaded);
  const model = $("homeModel");
  model.textContent = loaded ? "已加载" : "未加载";
  model.style.color = loaded ? "var(--ink)" : "#b45309";
  $("homeModelSub").textContent = loaded
    ? "LightGBM 撤稿风险 · AUC 0.856"
    : "模型文件缺失 · 风险徽章已停用";

  $("homeHist").textContent = getAskCount();

  const lib = $("homeLib");
  if (online) {
    lib.textContent = "3800万+";
    $("homeLibSub").textContent = "PubMed 收录 · 实时检索";
  } else {
    lib.textContent = (h && h.corpus_size) || "11";
    $("homeLibSub").textContent = "离线语料篇数 · 断网可用";
  }
}

/* 最近提问列表（支持 今日 / 全部 切换） */
let recentMode = "all";

function renderRecent() {
  const list = $("recentList");
  list.innerHTML = "";
  let h = getHistory();
  if (recentMode === "today") {
    const t = new Date(); t.setHours(0, 0, 0, 0);
    h = h.filter((it) => it.time >= t.getTime());
  }
  if (!h.length) {
    list.innerHTML = '<p class="recent-empty">暂无提问，从上方搜索框开始</p>';
    return;
  }
  h.slice(0, 6).forEach((it) => {
    const div = document.createElement("div");
    div.className = "recent-item";
    let color = "#a7b0bf";
    if (it.conflict) color = "#f59e0b";
    else if (it.verdict === "证据倾向支持") color = "#16a34a";
    else if (it.verdict === "证据倾向不支持") color = "#ef4444";
    const t = new Date(it.time);
    const hh = String(t.getHours()).padStart(2, "0");
    const mm = String(t.getMinutes()).padStart(2, "0");
    div.innerHTML = `
      <span class="recent-dot" style="background:${color}"></span>
      <span class="recent-q">${esc(it.query)}</span>
      <span class="recent-meta">
        <span class="recent-verdict" style="color:${color}">${esc(it.verdict)}</span>
        <span>${hh}:${mm}</span>
      </span>
    `;
    list.appendChild(div);
  });
}

/* 使用统计（累计次数独立计数，不受历史 20 条上限影响） */
function renderUsage() {
  const h = getHistory();
  $("usageTotal").textContent = getAskCount();
  if (h.length) {
    const avgMs = h.reduce((a, b) => a + (b.elapsedMs || 0), 0) / h.length;
    $("usageAvg").textContent = avgMs >= 1000 ? (avgMs / 1000).toFixed(1) + "s" : Math.round(avgMs) + "ms";
    const confs = h.map((x) => Number(x.confidence)).filter((n) => !isNaN(n) && n > 0);
    $("usageConf").textContent = confs.length ? Math.round(confs.reduce((a, b) => a + b, 0) / confs.length) : "–";
    const cf = h.filter((x) => x.conflict).length;
    $("usageConflict").textContent = cf ? cf + " 次" : "无";
  } else {
    $("usageAvg").textContent = "–";
    $("usageConf").textContent = "–";
    $("usageConflict").textContent = "–";
  }
}

/* 问答活动热力图：近 52 周，GitHub 风格绿色格子 */
function renderHeatmap() {
  const wrap = $("heatmap");
  wrap.innerHTML = "";
  const counts = {};
  getHistory().forEach((it) => {
    const d = new Date(it.time);
    const key = d.getFullYear() + "-" + d.getMonth() + "-" + d.getDate();
    counts[key] = (counts[key] || 0) + 1;
  });

  const today = new Date(); today.setHours(0, 0, 0, 0);
  const dow = (today.getDay() + 6) % 7; // 周一=0
  const monday = new Date(today); monday.setDate(today.getDate() - dow);
  const WEEKS = 52;
  const start = new Date(monday); start.setDate(monday.getDate() - (WEEKS - 1) * 7);

  const level = (n) => (n >= 5 ? 4 : n >= 3 ? 3 : n >= 2 ? 2 : n >= 1 ? 1 : 0);

  // 月份标签行
  const top = document.createElement("div");
  top.className = "heat-top";
  const CELL = 17; // 14px 格子 + 3px 间隙
  let lastMonth = -1;
  for (let w = 0; w < WEEKS; w++) {
    const colDate = new Date(start); colDate.setDate(start.getDate() + w * 7);
    if (colDate.getMonth() !== lastMonth) {
      lastMonth = colDate.getMonth();
      const m = document.createElement("span");
      m.className = "heat-month";
      m.style.left = 40 + w * CELL + "px";
      m.textContent = colDate.getMonth() + 1 + "月";
      top.appendChild(m);
    }
  }
  wrap.appendChild(top);

  // 主区：左侧星期标签 + 周列
  const main = document.createElement("div");
  main.className = "heat-main";
  const labels = document.createElement("div");
  labels.className = "heat-labels";
  ["周一", "", "周三", "", "周五", "", ""].forEach((txt) => {
    const s = document.createElement("span");
    s.className = "heat-label";
    s.textContent = txt;
    labels.appendChild(s);
  });
  main.appendChild(labels);

  const cols = document.createElement("div");
  cols.className = "heat-cols";
  for (let w = 0; w < WEEKS; w++) {
    const col = document.createElement("div");
    col.className = "heat-col";
    for (let r = 0; r < 7; r++) {
      const day = new Date(start);
      day.setDate(start.getDate() + w * 7 + r);
      const cell = document.createElement("div");
      cell.className = "heat-cell";
      if (day <= today) {
        const key = day.getFullYear() + "-" + day.getMonth() + "-" + day.getDate();
        const n = counts[key] || 0;
        if (n > 0) cell.classList.add("l" + level(n));
        cell.title = `${day.getMonth() + 1}月${day.getDate()}日 · ${n} 次提问`;
      } else {
        cell.style.visibility = "hidden";
      }
      col.appendChild(cell);
    }
    cols.appendChild(col);
  }
  main.appendChild(cols);
  wrap.appendChild(main);
}

function renderHome() {
  const histEl = $("homeHist");
  if (histEl) histEl.textContent = getAskCount();
  renderRecent();
  renderUsage();
  renderHeatmap();
}

/* 首页仪表盘与结果区互斥显示 */
function syncHome() {
  const busy = !$("loading").classList.contains("hidden");
  const hasResult = !$("result").classList.contains("hidden");
  $("homeDash").classList.toggle("hidden", busy || hasResult);
}

function showDashboard() {
  $("result").classList.add("hidden");
  $("error").classList.add("hidden");
  $("loading").classList.add("hidden");
  syncHome();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function renderPico(pico) {
  if (!pico) return;
  const set = (id, arr) => {
    $(id).textContent = arr && arr.length ? arr.join(" · ") : "未明确";
  };
  set("picoP", pico.population);
  set("picoI", pico.intervention);
  set("picoC", pico.comparison);
  set("picoO", pico.outcome);
}

/* ---------- 置信度等级标签 ---------- */
const CONF_TIERS = [
  { min: 80, label: "高", color: "#038f4a", text: "#fff", desc: "结果高度可信，可直接采信" },
  { min: 60, label: "中", color: "#4b97b8", text: "#fff", desc: "结果基本可信，建议复核" },
  { min: 40, label: "低", color: "#f5e400", text: "#1f2430", desc: "可信度偏低，重点排查" },
  { min: 0,  label: "极低", color: "#f0392c", text: "#fff", desc: "可信度极低，不建议采用" },
];
const CONF_NA = { label: "未分级", color: "#a7a7a7", text: "#fff", desc: "数据不足，无法评估" };

function renderConfidence(confidence) {
  const tag = $("confTag");
  const score = $("confScore");
  const desc = $("confDesc");
  const tier = confidence ? CONF_TIERS.find((t) => confidence >= t.min) : CONF_NA;
  tag.textContent = tier.label;
  tag.style.background = tier.color;
  tag.style.color = tier.text;
  score.textContent = confidence ? confidence : "–";
  score.style.color = tier.color;
  desc.textContent = tier.desc;
}

function renderDist(dist) {
  const bar = $("distBar");
  const legend = $("distLegend");
  bar.innerHTML = "";
  legend.innerHTML = "";
  const total = GRADE_ORDER.reduce((a, k) => a + (dist[k] || 0), 0) || 1;
  GRADE_ORDER.forEach((k) => {
    const v = dist[k] || 0;
    if (v === 0) return;
    const pct = (v / total) * 100;
    const seg = document.createElement("div");
    seg.className = "dist-seg";
    seg.style.width = pct + "%";
    seg.style.background = GRADE_COLOR[k];
    seg.title = `${GRADE_ZH[k]}：${v} 篇`;
    bar.appendChild(seg);

    const item = document.createElement("span");
    item.innerHTML = `<i class="swatch" style="background:${GRADE_COLOR[k]}"></i>${GRADE_ZH[k]} · ${v} 篇`;
    legend.appendChild(item);
  });
}

function renderDocs(results) {
  const list = $("docList");
  list.innerHTML = "";
  $("docCount").textContent = `${results.length} 篇文献`;
  results.forEach((d) => {
    const div = document.createElement("div");
    div.className = "doc-item";

    const grade = GRADE_ZH[d.grade] || "未分级";
    const color = GRADE_COLOR[d.grade] || "#A7A7A7";
    const url = d.pmid
      ? `https://pubmed.ncbi.nlm.nih.gov/${d.pmid}/`
      : "#";

    const authors = (d.authors || []).slice(0, 2).join(", ");
    const metaParts = [
      d.journal, d.year,
      `${STYPE_ZH[d.study_type] || "其他"} · 证据 ${grade}`,
      authors,
    ].filter(Boolean).join(" · ");

    const INTEGRITY_ZH = { retracted: "已撤稿", concern: "存疑", corrected: "已更正" };
    const integrity = d.integrity && d.integrity !== "ok" ? d.integrity : null;
    const integBadge = integrity
      ? `<span class="integrity-badge integrity-${integrity}">${INTEGRITY_ZH[integrity]}</span>`
      : "";

    // 撤稿风险徽章（LightGBM 模型预测，score 为 0-1 概率）
    const RISK_COLOR = { "高": "#F03A2C", "中高": "#F5E400", "中低": "#4B97B8", "低": "#038F49" };
    let riskBadge = "";
    if (d.risk && typeof d.risk.score === "number") {
      const pct = Math.round(d.risk.score * 100);
      const lvl = d.risk.level || (pct >= 60 ? "高" : pct >= 40 ? "中高" : pct >= 20 ? "中低" : "低");
      const rc = RISK_COLOR[lvl] || "#A7A7A7";
      const txt = rc === "#F5E400" ? "#1f2430" : "#fff";
      riskBadge = `<span class="risk-badge" style="background:${rc};color:${txt}" title="撤稿风险模型预测（仅供参考）">风险 ${pct}%</span>`;
    }

    div.innerHTML = `
      <p class="doc-title"><a href="${url}" target="_blank" rel="noopener">${esc(d.title)}</a></p>
      <div class="doc-meta">
        <span class="badge" style="background:${color};color:${contrastText(color)}">${grade}</span>
        ${integBadge}
        ${riskBadge}
        <span>${esc(metaParts)}</span>
        ${d.pmid ? `<span>PMID ${esc(d.pmid)}</span>` : ""}
      </div>
      ${d.abstract ? `<div class="doc-abstract">${esc(d.abstract)}</div>` : ""}
      <div class="rel-bar"><div class="rel-fill" style="width:${Math.max(2, d.relevance || 0)}%"></div></div>
    `;
    list.appendChild(div);
  });
}

async function ask(query) {
  if (!query.trim()) return;
  $("query").value = query;
  $("askBtn").disabled = true;
  $("result").classList.add("hidden");
  $("error").classList.add("hidden");
  $("loading").classList.remove("hidden");
  syncHome();
  window.scrollTo({ top: 0, behavior: "smooth" });
  const started = performance.now();

  try {
    const r = await fetch("/api/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, retmax: settings.retmax }),
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({}));
      throw new Error(e.detail || `请求失败（${r.status}）`);
    }
    const data = await r.json();
    const elapsed = performance.now() - started;
    setStatus(data.online);
    renderStats(data, elapsed, data.evidence);
    renderPico(data.pico);
    renderAnswer(data);
    renderDist(data.evidence_distribution || {});
    renderDocs(data.results || []);
    recordHistory(query, data.evidence, elapsed);
    $("loading").classList.add("hidden");
    $("result").classList.remove("hidden");
    syncHome();
  } catch (err) {
    $("loading").classList.add("hidden");
    $("error").textContent = "出错了：" + err.message;
    $("error").classList.remove("hidden");
    syncHome();
  } finally {
    $("askBtn").disabled = false;
  }
}

$("askBtn").addEventListener("click", () => ask($("query").value));
$("query").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ask($("query").value);
});
document.querySelectorAll(".chip").forEach((c) =>
  c.addEventListener("click", () => ask(c.dataset.q))
);

/* ---------- 设置 ---------- */
const SETTINGS_KEY = "medlit.settings";
const defaultSettings = { retmax: 20, showAbstract: true };

function loadSettings() {
  try {
    const s = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    return Object.assign({}, defaultSettings, s);
  } catch {
    return { ...defaultSettings };
  }
}

function saveSettings() {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

const settings = loadSettings();

function applySettingsUI() {
  document.querySelectorAll("#retmaxSeg button").forEach((b) =>
    b.classList.toggle("active", Number(b.dataset.v) === settings.retmax)
  );
  $("showAbstract").checked = settings.showAbstract;
  $("docList").classList.toggle("hide-abstract", !settings.showAbstract);
}

document.querySelectorAll("#retmaxSeg button").forEach((b) =>
  b.addEventListener("click", () => {
    settings.retmax = Number(b.dataset.v);
    saveSettings();
    applySettingsUI();
  })
);
$("showAbstract").addEventListener("change", (e) => {
  settings.showAbstract = e.target.checked;
  saveSettings();
  applySettingsUI();
});

/* ---------- 通知 / 历史记录 ---------- */
const HISTORY_KEY = "medlit.history";

function getHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
  } catch {
    return [];
  }
}

function recordHistory(query, ev, elapsedMs) {
  const h = getHistory();
  h.unshift({
    query,
    verdict: ev ? ev.verdict : "–",
    confidence: ev ? ev.confidence : "–",
    conflict: ev ? !!ev.conflict : false,
    time: Date.now(),
    elapsedMs: Math.round(elapsedMs),
  });
  localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(0, 20)));
  localStorage.setItem(ASKCOUNT_KEY, String(getAskCount() + 1));
  updateNotifBadge();
  renderHome();
}

function updateNotifBadge() {
  const n = getHistory().length;
  const badge = $("notifBadge");
  if (n > 0) {
    badge.textContent = n > 99 ? "99+" : String(n);
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }
}

function renderHistory() {
  const list = $("notifList");
  list.innerHTML = "";
  const h = getHistory();
  if (!h.length) {
    list.innerHTML = '<p class="notif-empty">暂无问答记录</p>';
    return;
  }
  h.forEach((it) => {
    const div = document.createElement("div");
    div.className = "notif-item";
    const cls = it.conflict ? "conflict" : (it.verdict === "证据倾向支持" ? "support" : "neutral");
    const color = it.conflict ? "#f59e0b" : (it.verdict === "证据倾向支持" ? "#16a34a" : "#8a93a3");
    const t = new Date(it.time);
    const hh = String(t.getHours()).padStart(2, "0");
    const mm = String(t.getMinutes()).padStart(2, "0");
    div.innerHTML = `
      <p class="notif-query">${esc(it.query)}</p>
      <div class="notif-meta">
        <span class="notif-verdict" style="color:${color}">${esc(it.verdict)}</span>
        <span>置信度 ${it.confidence}</span>
        <span>${it.elapsedMs}ms</span>
        <span>${hh}:${mm}</span>
      </div>
    `;
    list.appendChild(div);
  });
  const clear = document.createElement("button");
  clear.className = "notif-clear";
  clear.textContent = "清空记录";
  clear.addEventListener("click", () => {
    localStorage.removeItem(HISTORY_KEY);
    updateNotifBadge();
    renderHistory();
    renderHome();
  });
  list.appendChild(clear);
}

/* ---------- 抽屉开合 ---------- */
function openDrawer(name) {
  const isSettings = name === "settings";
  const drawer = $(isSettings ? "settingsDrawer" : "notifDrawer");
  const mask = document.querySelector(`.drawer-mask[data-close="${name}"]`);
  drawer.classList.remove("hidden");
  mask.classList.remove("hidden");
  if (!isSettings) renderHistory();
}
function closeDrawer(name) {
  const isSettings = name === "settings";
  $(isSettings ? "settingsDrawer" : "notifDrawer").classList.add("hidden");
  document.querySelector(`.drawer-mask[data-close="${name}"]`).classList.add("hidden");
}

document.querySelectorAll(".drawer-close, .drawer-mask").forEach((el) =>
  el.addEventListener("click", () => closeDrawer(el.dataset.close))
);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    ["settings", "notif"].forEach(closeDrawer);
  }
});

/* ---------- 左侧栏 ---------- */
$("navHome").addEventListener("click", () => {
  showDashboard();
  $("query").focus();
});
$("navNew").addEventListener("click", () => {
  $("query").value = "";
  showDashboard();
  $("query").focus();
});
$("navSettings").addEventListener("click", () => openDrawer("settings"));
$("navNotifications").addEventListener("click", () => openDrawer("notif"));

/* 最近提问：今日 / 全部 切换 */
document.querySelectorAll("#recentSeg button").forEach((b) =>
  b.addEventListener("click", () => {
    recentMode = b.dataset.v;
    document.querySelectorAll("#recentSeg button").forEach((x) =>
      x.classList.toggle("active", x === b)
    );
    renderRecent();
  })
);

renderHome();
applySettingsUI();
updateNotifBadge();
checkHealth();
