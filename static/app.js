const GRADE_ZH = {
  High: "高", Moderate: "中", Low: "低", "Very low": "极低", "N/A": "未分级",
};
const GRADE_COLOR = {
  High: "#85D485", Moderate: "#AD85D5", Low: "#F9AB7A",
  "Very low": "#D45E85", "N/A": "#94a3b8",
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
  } catch {
    setStatus(false);
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
  const statCards = document.querySelectorAll(".stat-card");
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

  renderRing(ev ? ev.confidence : 0, state);
}

/* ---------- PICO 问题理解 ---------- */
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

/* ---------- 置信度圆环 ---------- */
const RING_R = 52;
const RING_C = 2 * Math.PI * RING_R;
const RING_COLORS = {
  support: ["#86efac", "#16a34a"],
  against: ["#fca5a5", "#ef4444"],
  conflict: ["#fcd34d", "#f59e0b"],
  neutral: ["#a5b4fc", "#4f46e5"],
};

function renderRing(confidence, state) {
  const val = Math.max(0, Math.min(100, confidence || 0));
  const ring = $("ringValue");
  ring.style.strokeDasharray = RING_C;
  ring.style.strokeDashoffset = RING_C * (1 - val / 100);
  const [light, dark] = RING_COLORS[state] || RING_COLORS.neutral;
  $("ringStop0").setAttribute("stop-color", light);
  $("ringStop1").setAttribute("stop-color", dark);
  $("ringNum").textContent = val;
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
    const color = GRADE_COLOR[d.grade] || "#94a3b8";
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

    div.innerHTML = `
      <p class="doc-title"><a href="${url}" target="_blank" rel="noopener">${esc(d.title)}</a></p>
      <div class="doc-meta">
        <span class="badge" style="background:${color};color:${contrastText(color)}">${grade}</span>
        ${integBadge}
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
  } catch (err) {
    $("loading").classList.add("hidden");
    $("error").textContent = "出错了：" + err.message;
    $("error").classList.remove("hidden");
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
  updateNotifBadge();
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

/* ---------- 左侧图标栏 ---------- */
$("navHome").addEventListener("click", () => {
  window.scrollTo({ top: 0, behavior: "smooth" });
  $("query").focus();
});
$("navNew").addEventListener("click", () => {
  $("query").value = "";
  $("query").focus();
});
$("navSettings").addEventListener("click", () => openDrawer("settings"));
$("navNotifications").addEventListener("click", () => openDrawer("notif"));

applySettingsUI();
updateNotifBadge();
checkHealth();
