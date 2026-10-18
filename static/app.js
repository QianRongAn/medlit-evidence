const GRADE_ZH = {
  High: "高", Moderate: "中", Low: "低", "Very low": "极低", "N/A": "未分级",
};
// 沉静的分级配色；类别含义同时用文字表达
const GRADE_COLOR = {
  High: "#377F78", Moderate: "#4665B8", Low: "#80652C",
  "Very low": "#A26761", "N/A": "#65758C",
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
  notice: "学术通知",
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
  unassessed: { label: "未评估", color: "#8f8f88" },
};

function motionBehavior() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ? "auto" : "smooth";
}

function focusSource(pmid) {
  const target = $(pmid ? "source-" + pmid : "sourcePanel");
  if (!target) return;
  target.scrollIntoView({ behavior: motionBehavior(), block: "center" });
  target.focus({ preventScroll: true });
  target.classList.add("source-highlight");
  setTimeout(() => target.classList.remove("source-highlight"), 2400);
}

function toggleReadingMode() {
  const enabled = !$("result").classList.contains("reading-mode");
  $("result").classList.toggle("reading-mode", enabled);
  $("readingMode").ariaPressed = String(enabled);
  $("readingMode").textContent = enabled ? "退出舒适阅读" : "舒适阅读";
}

function renderAnswer(data) {
  const body = $("answerBody");
  body.innerHTML = "";
  $("answerNotice").textContent = data.mode === "llm"
    ? "引用来源与对应原句已校验；生成摘要的语义是否受原文支持仍需核对。"
    : data.llm_fallback_reason === "citation_validation_failed"
      ? "生成结果未通过引用校验，已改用摘要摘录。"
      : data.llm_fallback_reason === "llm_unavailable" ? "生成服务不可用，已改用摘要摘录。" : "";
  if (data.sentences && data.sentences.length) {
    data.sentences.forEach((s) => {
      const p = document.createElement("p");
      p.className = "answer-sentence";
      const pol = POLARITY.unassessed;
      const mark = document.createElement("span");
      mark.className = "pol-mark";
      mark.style.color = pol.color;
      mark.title = "结论方向：" + pol.label;
      p.appendChild(mark);
      p.appendChild(document.createTextNode(s.sentence + " "));
      const cite = document.createElement("a");
      cite.className = "cite";
      cite.textContent = "PMID " + s.pmid;
      if (s.pmid) {
        cite.href = "https://pubmed.ncbi.nlm.nih.gov/" + s.pmid + "/";
        cite.target = "_blank";
        cite.rel = "noopener";
      }
      p.appendChild(cite);
      if (/^[1-9][0-9]*$/.test(String(s.pmid || ""))) {
        const locate = document.createElement("button");
        locate.className = "locate-source";
        locate.textContent = "定位文献 ↘";
        locate.title = "定位本页文献 PMID " + s.pmid;
        locate.addEventListener("click", () => focusSource(s.pmid));
        p.appendChild(locate);
      }
      body.appendChild(p);
      if (data.mode === "llm" && s.quote) {
        const quote = document.createElement("blockquote");
        quote.className = "source-quote";
        quote.textContent = "对应摘要原句：" + s.quote;
        body.appendChild(quote);
      }
    });
  } else {
    const p = document.createElement("p");
    p.textContent = data.answer || "未能生成回答，请换一种问法。";
    body.appendChild(p);
  }
  $("modeBadge").textContent =
    data.mode === "llm" ? "LLM 摘要整理（待核对）" : `摘要摘录（${data.online ? "PubMed" : "演示语料"}）`;
}

function renderStats(data, elapsedMs, ev) {
  // 未经验证的方向与置信度不显示为数字或无冲突。
  $("confidenceNum").textContent = "–";

  // 未验证的证据方向保持待核对状态。
  // 保留原有判定文字，不通过主题色暗示支持或反对。
  $("verdictText").textContent = ev ? ev.verdict.replace(/^证据/, "") : "待核对";
  const verdictCard = $("statVerdict");
  verdictCard.classList.remove("tone-cream", "tone-pink", "tone-salmon", "tone-mint");
  verdictCard.classList.add("tone-mint");
  $("verdictSub").textContent = "尚未验证，暂不评分";
  $("assessmentNote").textContent = ev ? ev.assessment_note : "证据方向尚未评估";
  $("polarityLine").textContent = ev
    ? `方向未评估 ${ev.unassessed_count || 0} 篇`
    : "";

  // 卡 3：文献命中
  $("hitNum").textContent = data.total.toLocaleString();
  $("hitSub").textContent = `筛选纳入 ${data.results.length} 篇 · ${data.online ? "PubMed 在线" : "离线语料"}`;

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

  renderConfidence();
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
  svc.style.color = online ? "#287567" : "#95631b";
  $("homeSvcSub").textContent = online
    ? "PubMed E-utilities 实时检索已连通"
    : "联网失败 · 自动回退内置示例语料";

  const loaded = !!(h && h.model_loaded);
  const model = $("homeModel");
  model.textContent = loaded ? "已加载" : "未加载";
  model.style.color = loaded ? "#273449" : "#95631b";
  $("homeModelSub").textContent = loaded
    ? "研究模型分数 · 未校准"
    : "模型不可用 · 分数未显示";

  $("homeHist").textContent = getAskCount();

  const lib = $("homeLib");
  if (online) {
    lib.textContent = "已连接";
    $("homeLibSub").textContent = "PubMed · 按问题实时检索";
  } else {
    lib.textContent = h && Number.isInteger(h.corpus_size) ? h.corpus_size : "–";
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
    let color = "#a6a6a0";
    if (it.conflict) color = "#f5a800";
    else if (it.verdict === "证据倾向支持") color = "#12b76a";
    else if (it.verdict === "证据倾向不支持") color = "#f24726";
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
    $("usageConflict").textContent = cf ? cf + " 次" : "未评估";
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
  $("workspaceIntro").classList.toggle("hidden", busy || hasResult);
  document.body?.classList.toggle("research-active", busy || hasResult);
}

function showDashboard() {
  cancelSearch();
  $("result").classList.add("hidden");
  $("error").classList.add("hidden");
  $("loading").classList.add("hidden");
  syncHome();
  window.scrollTo({ top: 0, behavior: motionBehavior() });
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

function renderScreening(data) {
  const screening = data.screening;
  const excluded = data.excluded_results || [];
  const note = $("screeningNote");
  if (!screening) {
    note.textContent = "";
  } else {
    const issues = {
      unmapped_chinese_terms: "有未映射的中文词项",
      ambiguous_alternatives: "尚不能解析或者条件",
      unsupported_numeric_constraint: "尚不能解析数字条件",
      negated_population_query: "尚不能解析排除人群条件",
      unparsed_exclusion: "尚不能解析排除条件",
      no_content_terms: "缺少可检索的医学词项",
    };
    const detail = (screening.issues || []).map((key) => issues[key] || "查询条件待明确").join("；");
    note.textContent = `候选 ${screening.candidate_count} 篇，词项筛选命中 ${screening.matched_count} 篇，展示 ${screening.included_count} 篇，未纳入 ${screening.excluded_count} 篇。`
      + (detail ? detail + "。" : "")
      + (screening.unmapped_terms && screening.unmapped_terms.length ? "未映射：" + screening.unmapped_terms.join("、") + "。" : "")
      + (screening.note || "");
  }
  $("excludedSources").classList.toggle("hidden", excluded.length === 0);
  $("excludedCount").textContent = `未纳入的候选 · ${excluded.length} 篇`;
  const list = $("excludedList");
  list.innerHTML = "";
  const reasons = {
    missing_population: "人群词项未覆盖", missing_intervention: "干预词项未覆盖",
    missing_comparison: "对照词项未覆盖", missing_outcome: "摘要中未覆盖所问结局",
    insufficient_lexical_coverage: "其他查询词覆盖不足", missing_abstract: "缺少摘要",
    unsupported_query: "查询条件尚未完整解析",
  };
  excluded.forEach((d) => {
    const item = document.createElement("div");
    item.className = "doc-item";
    const why = ((d.screening && d.screening.reasons) || []).map((key) => reasons[key] || key).join("；");
    const pmid = String(d.pmid || "");
    const title = /^[1-9][0-9]{0,9}$/.test(pmid)
      ? `<a href="https://pubmed.ncbi.nlm.nih.gov/${pmid}/" target="_blank" rel="noopener">${esc(d.title || "无标题")}</a>`
      : esc(d.title || "无标题");
    item.innerHTML = `<p class="doc-title">${title}</p><div>${integrityBadges(d)}</div><p class="doc-meta">未纳入原因：${esc(why)}</p><div>${integrityLinks(d)}</div>`;
    list.appendChild(item);
  });
}

/* 未完成语义对齐与独立验证前，不渲染旧版置信度。 */
function renderConfidence() {
  const tag = $("confTag");
  const score = $("confScore");
  const desc = $("confDesc");
  tag.textContent = "未评估";
  tag.style.color = "#5F6E83";
  score.textContent = "–";
  score.style.color = "#4665b8";
  desc.textContent = "研究类型不等于结论可信度";
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

function modelScoreBadge(score) {
  // 旧版概率载荷也不展示，避免把 0–1 误当作新版 0–100 分数。
  if (!score || score.kind !== "research_model_score" || score.calibrated !== false
      || !Array.isArray(score.scale) || score.scale[0] !== 0 || score.scale[1] !== 100
      || typeof score.score !== "number" || !Number.isFinite(score.score)
      || score.score < 0 || score.score > 100) return "";
  return `<span class="risk-badge" style="background:#e8edf7;color:#32415e" title="仅供人工排序；未校准，不代表未来撤稿概率">研究分数 ${score.score.toFixed(1)} / 100</span>`;
}

function integrityBadges(doc) {
  const labels = { retracted: "已撤稿", concern: "存疑", corrected: "有更正/重发", notice: "学术通知" };
  const flags = new Set(doc.integrity_flags || []);
  if (doc.integrity && doc.integrity !== "ok") flags.add(doc.integrity);
  if (doc.is_notice) flags.add("notice");
  return Object.keys(labels).filter((key) => flags.has(key)).map((key) =>
    `<span class="integrity-badge integrity-${key}">${labels[key]}</span>`
  ).join("");
}

function integrityLinks(doc) {
  const labels = {
    RetractionIn: "撤稿通知", RetractionOf: "所涉原文",
    ExpressionOfConcernIn: "存疑通知", ExpressionOfConcernFor: "所涉原文",
    ErratumIn: "更正通知", ErratumFor: "所涉原文",
    CorrectedandRepublishedIn: "更正重发版", CorrectedandRepublishedFrom: "更正前版本",
    RetractedandRepublishedIn: "重发版", RetractedandRepublishedFrom: "已撤稿原版",
  };
  return (doc.integrity_relations || []).filter((r) => labels[r.ref_type]).map((r) => {
    const label = labels[r.ref_type];
    const pmid = String(r.pmid || "");
    return /^[1-9][0-9]{0,9}$/.test(pmid)
      ? `<a class="doc-pmid" href="https://pubmed.ncbi.nlm.nih.gov/${pmid}/" target="_blank" rel="noopener">${label} · PMID ${pmid}</a>`
      : `<span class="doc-meta">${label}：${esc(r.citation || "未提供关联 PMID")}</span>`;
  }).join(" · ");
}

function renderDocs(results) {
  const list = $("docList");
  list.innerHTML = "";
  $("docCount").textContent = `${results.length} 篇文献`;
  results.forEach((d, index) => {
    const div = document.createElement("div");
    div.className = "doc-item";
    if (/^[1-9][0-9]*$/.test(String(d.pmid || ""))) div.id = "source-" + d.pmid;
    div.tabIndex = -1;
    div.style.setProperty?.("--entry-delay", Math.min(index, 5) * 45 + "ms");

    const grade = GRADE_ZH[d.grade] || "未分级";
    const color = GRADE_COLOR[d.grade] || "#C3C2BC";

    const authors = (d.authors || []).slice(0, 2).join(", ");
    const metaParts = [
      d.journal, d.year,
      `${STYPE_ZH[d.study_type] || "其他"} · 证据 ${grade}`,
      authors,
    ].filter(Boolean).join(" · ");

    const integBadge = integrityBadges(d);

    const riskBadge = modelScoreBadge(d.risk);

    const pmidUrl = d.pmid ? `https://pubmed.ncbi.nlm.nih.gov/${d.pmid}/` : "";
    div.innerHTML = `
      <div class="doc-topline"><span>文献 ${String(index + 1).padStart(2, "0")}</span><span>PUBLICATION</span></div>
      <p class="doc-title"><a href="${pmidUrl || "#"}" target="_blank" rel="noopener">${esc(d.title)}</a></p>
      <div class="doc-meta">
        <span class="badge" style="background:${color};color:${contrastText(color)}">${grade}</span>
        ${integBadge}
        ${riskBadge}
      </div>
      <div class="doc-meta">${esc(metaParts)}</div>
      ${d.abstract ? `<div class="abstract-block"><div class="doc-abstract abstract-preview" aria-hidden="true">${esc(d.abstract)}</div><details class="abstract-details"><summary><span class="when-closed">阅读完整摘要</span><span class="when-open">收起摘要</span><span class="abstract-plus" aria-hidden="true">+</span></summary><div class="doc-abstract abstract-full">${esc(d.abstract)}</div></details></div>` : ""}
      ${d.pmid ? `<a class="doc-pmid" href="${pmidUrl}" target="_blank" rel="noopener">PMID ${esc(d.pmid)}</a>` : ""}
      <div>${integrityLinks(d)}</div>
      <div class="doc-meta">查询词项覆盖 ${Number(d.relevance || 0).toFixed(1)}% · 不代表临床适用性</div>
      <div class="rel-bar"><div class="rel-fill" style="width:${Math.max(2, d.relevance || 0)}%"></div></div>
    `;
    list.appendChild(div);
  });
}

let activeRequest = null;
let loadingTimer = null;

function setSearchBusy(busy) {
  $("askBtn").disabled = busy;
  $("askBtn").classList.toggle("is-loading", busy);
  $("askLabel").textContent = busy ? "检索中…" : "检索证据";
  $("searchComposer").ariaBusy = String(busy);
}

function cancelSearch() {
  if (!activeRequest) return;
  const request = activeRequest;
  activeRequest = null;
  request.abort();
  clearInterval(loadingTimer);
  loadingTimer = null;
  $("loading").classList.add("hidden");
  setSearchBusy(false);
  syncHome();
}

async function ask(query) {
  if (!query.trim() || activeRequest) return;
  const controller = new AbortController();
  activeRequest = controller;
  $("query").value = query;
  $("topQuery").value = query;
  setSearchBusy(true);
  $("result").classList.add("hidden");
  $("error").classList.add("hidden");
  $("loading").classList.remove("hidden");
  syncHome();
  window.scrollTo({ top: 0, behavior: motionBehavior() });
  const started = performance.now();
  $("loadingElapsed").textContent = "0s";
  loadingTimer = setInterval(() => {
    $("loadingElapsed").textContent = Math.floor((performance.now() - started) / 1000) + "s";
  }, 1000);

  try {
    const r = await fetch("/api/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, retmax: settings.retmax }),
      signal: controller.signal,
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({}));
      throw new Error(e.detail || `请求失败（${r.status}）`);
    }
    const data = await r.json();
    if (activeRequest !== controller) return;
    const elapsed = performance.now() - started;
    setStatus(data.online);
    renderStats(data, elapsed, data.evidence);
    renderPico(data.pico);
    renderScreening(data);
    renderAnswer(data);
    renderDist(data.evidence_distribution || {});
    renderDocs(data.results || []);
    recordHistory(query, data.evidence, elapsed);
    $("loading").classList.add("hidden");
    $("result").classList.remove("hidden");
    syncHome();
  } catch (err) {
    if (activeRequest !== controller || controller.signal.aborted) return;
    $("loading").classList.add("hidden");
    $("error").textContent = "出错了：" + err.message;
    $("error").classList.remove("hidden");
    syncHome();
  } finally {
    if (activeRequest === controller) {
      clearInterval(loadingTimer);
      loadingTimer = null;
      activeRequest = null;
      setSearchBusy(false);
    }
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
    const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (!Array.isArray(history)) return [];
    return history.filter((it) => it && typeof it === "object").map((it) => ({
      ...it,
      verdict: it.assessment_version === "2" ? it.verdict : "旧版判定已停用",
      confidence: null,
      conflict: null,
    }));
  } catch {
    return [];
  }
}

function recordHistory(query, ev, elapsedMs) {
  const h = getHistory();
  h.unshift({
    query,
    verdict: ev ? ev.verdict : "–",
    assessment_version: ev ? ev.assessment_version : null,
    confidence: null,
    conflict: null,
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
    const color = it.conflict ? "#f5a800" : (it.verdict === "证据倾向支持" ? "#12b76a" : "#8f8f88");
    const t = new Date(it.time);
    const hh = String(t.getHours()).padStart(2, "0");
    const mm = String(t.getMinutes()).padStart(2, "0");
    div.innerHTML = `
      <p class="notif-query">${esc(it.query)}</p>
      <div class="notif-meta">
        <span class="notif-verdict" style="color:${color}">${esc(it.verdict)}</span>
        <span>置信度未评估</span>
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
let activeDrawer = null;
let drawerOpener = null;
function openDrawer(name) {
  if (activeDrawer && activeDrawer !== name) closeDrawer(activeDrawer);
  drawerOpener = document.activeElement;
  activeDrawer = name;
  const isSettings = name === "settings";
  const drawer = $(isSettings ? "settingsDrawer" : "notifDrawer");
  const mask = document.querySelector(`.drawer-mask[data-close="${name}"]`);
  drawer.classList.remove("hidden");
  mask.classList.remove("hidden");
  if (!isSettings) renderHistory();
  document.querySelectorAll(".topbar, .nav-rail, main").forEach((el) => { el.inert = true; });
  document.body.classList.add("drawer-open");
  drawer.focus();
}
function closeDrawer(name) {
  const isSettings = name === "settings";
  $(isSettings ? "settingsDrawer" : "notifDrawer").classList.add("hidden");
  document.querySelector(`.drawer-mask[data-close="${name}"]`).classList.add("hidden");
  if (activeDrawer === name) {
    activeDrawer = null;
    document.querySelectorAll(".topbar, .nav-rail, main").forEach((el) => { el.inert = false; });
    document.body.classList.remove("drawer-open");
    if (drawerOpener) drawerOpener.focus();
    drawerOpener = null;
  }
}

document.querySelectorAll(".drawer-close, .drawer-mask").forEach((el) =>
  el.addEventListener("click", () => closeDrawer(el.dataset.close))
);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    ["settings", "notif"].forEach(closeDrawer);
  }
  if (e.key === "Tab" && activeDrawer) {
    const drawer = $(activeDrawer === "settings" ? "settingsDrawer" : "notifDrawer");
    const controls = [...drawer.querySelectorAll('button, input, a[href], [tabindex="0"]')].filter((el) => !el.disabled);
    if (!controls.length) { e.preventDefault(); drawer.focus(); return; }
    const first = controls[0], last = controls[controls.length - 1];
    if (!controls.includes(document.activeElement) || (!e.shiftKey && document.activeElement === last)) {
      e.preventDefault(); (e.shiftKey ? last : first).focus();
    } else if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    }
  }
});

/* ---------- 顶栏 ---------- */
$("navHome").addEventListener("click", () => {
  showDashboard();
  $("query").focus();
});
$("navNew").addEventListener("click", () => {
  $("query").value = "";
  $("topQuery").value = "";
  showDashboard();
  $("query").focus();
});
$("navSettings").addEventListener("click", () => openDrawer("settings"));
$("navNotifications").addEventListener("click", () => openDrawer("notif"));

/* 顶栏搜索框：回车直接提问 */
$("topQuery").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const q = $("topQuery").value.trim();
    if (q) ask(q);
  }
});

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

// Compact navigation shares the existing workspace actions.
$("railHome").addEventListener("click", () => { showDashboard(); $("query").focus(); });
$("railHistory").addEventListener("click", () => openDrawer("notif"));
$("railSettings").addEventListener("click", () => openDrawer("settings"));

$("readingMode").addEventListener("click", toggleReadingMode);
$("jumpSources").addEventListener("click", () => focusSource(null));
$("cancelSearch").addEventListener("click", () => { cancelSearch(); $("query").focus(); });
